import os
import random
import string

import aexpect
from avocado.utils import process
from virttest import env_process, error_context, utils_disk, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test When running virtiofsd as non-root,map a range of UIDs/GIDs
     from host to virtiofsd user namespace.
    Steps:
        1. Create a common user on host.
        2. Create a directory on host as a shared dir and give xw permission.
        3. Get the common user's sub UID and GID range.
        4. Start virtiofs daemon with the common user and mapping the virtiofsd's
        user namespace to the actual common users' sub UID and GID range.
        5. start vm.
        6. In the guest, mount virtiofsd and create a common user.
        7. Create a file seperately with root and the common user
        8. Check the file's uid and gid seperately in guest and host.
        mapping: (guest)root<->(host)common user;
                 (guest)u1<->(host)subuid+$uid_of_u1
        9. repeate step 4-7,the different is mapping only one subuid/subgid
         to virtiofsd user namespace.
        mapping: (guest)root<->(host)common user;
                 (guest)u1: Permission denied to create file

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_sub_uid_gid(id_type):
        """
        Get the host common user's sub uid/gid and count in host.
        """
        output = (
            process.system_output(
                "cat /etc/%s |grep %s" % (id_type, user_name), shell=True
            )
            .decode()
            .strip()
        )
        id_begin = output.split(":")[1]
        id_count = output.split(":")[2]
        return id_begin, id_count

    def create_file_in_guest(user_guest):
        """
        Create a file in the shared directory inside guest with
        root user or a common user.
        only for linux guest.
        """
        file_name = "file_" + "".join(
            random.sample(string.ascii_letters + string.digits, 3)
        )
        guest_file = os.path.join(fs_dest, file_name)
        error_context.context(
            "Create a file in shared dir " "with %s user." % user_guest, test.log.info
        )
        if user_guest != "root":
            if session.cmd_status("id %s" % user_guest) == 0:
                session.cmd(del_user_cmd % user_guest)
            session.cmd(add_user_cmd % user_guest)
            guest_user_session = vm.wait_for_login()
            guest_user_session.cmd("su %s" % user_guest)
            s = guest_user_session.cmd_status(create_file_cmd % guest_file)
            if map_type == "one_to_one" and s == 0:
                test.fail(
                    "Only mapping root user to host, so the common user"
                    " should have no permission to"
                    " create a file in the shared dir."
                )
            guest_user_session.close()
        else:
            session.cmd(create_file_cmd % guest_file)
        return file_name

    def get_expect_user_id(user_guest):
        """
        Get the expected file uid/gid in both guest and host.
        if the file is created by root,
         file's uid/gid should be the same with root user in guest,
         while it's uid_begin/gid_begin in host;
        if the file is created by a common user,
         uid/gid should be the same with the common user in guest,
         while it's uid_begin/gid_begin + ${id_common_user} in host.
        """
        error_context.context(
            "Get the user %s's uid:gid from guest." % user_guest, test.log.info
        )
        user_uid = session.cmd_output("id %s -u" % user_guest).strip()
        user_gid = session.cmd_output("id %s -g" % user_guest).strip()

        expect_id = {
            "guest": user_uid + ":" + user_gid,
            "host": "%s:%s"
            % (
                str(int(uid_begin) + int(user_uid)),
                str(int(gid_begin) + int(user_gid)),
            ),
        }
        test.log.info("The expected file's id is %s for %s", expect_id, user_guest)
        return expect_id

    def get_file_owner_id_guest(file_name):
        """
        Get the created file's uid and gid in guest.
        """
        error_context.context(
            "Get the file %s's uid:gid in guest." % file_name, test.log.info
        )
        cmd_get_file = "ls -l %s"
        guest_file = os.path.join(fs_dest, file_name)
        output_guest = session.cmd_output(cmd_get_file % guest_file).strip()
        owner_guest = output_guest.split()[2]
        group_guest = output_guest.split()[3]
        s, o = session.cmd_status_output("id %s -u" % owner_guest)
        if s:
            uid = owner_guest
        else:
            uid = o.strip()
        s, o = session.cmd_status_output("id %s -g" % group_guest)
        if s:
            gid = group_guest
        else:
            gid = o.strip()
        return uid + ":" + gid

    def get_file_owner_id_host(file_name):
        """
        Get the created file's uid and gid in host.
        """
        error_context.context(
            "Get the file %s's uid:gid in host." % file_name, test.log.info
        )
        cmd_get_file = "ls -l %s"
        host_file = os.path.join(shared_dir, file_name)
        output_host = (
            process.system_output(cmd_get_file % host_file, shell=True).decode().strip()
        )
        owner_host = output_host.split()[2]
        group_host = output_host.split()[3]
        if process.system("id %s -u" % owner_host, shell=True, ignore_status=True):
            uid = owner_host
        else:
            uid = (
                process.system_output("id %s -u" % owner_host, shell=True)
                .decode()
                .strip()
            )
        if process.system("id %s -g" % group_host, shell=True, ignore_status=True):
            gid = group_host
        else:
            gid = (
                process.system_output("id %s -g" % group_host, shell=True)
                .decode()
                .strip()
            )
        return uid + ":" + gid

    fs_target = params.get("fs_target")
    fs_dest = params.get("fs_dest")
    del_user_cmd = params["del_user_cmd"]
    add_user_cmd = params["add_user_cmd"]
    create_file_cmd = params.get("create_file_cmd")
    map_type = params.get("map_type")
    common_guest_user = params["new_user_guest"]
    vfsd_log_name = params["vfsd_log_name"]

    vm = None
    p_vfsd = None
    try:
        # start virtiofsd with user config in host
        error_context.context(
            "Create a common user and a shared dir in host.", test.log.info
        )
        user_name = params["new_user_host"]
        if process.system("id %s" % user_name, shell=True, ignore_status=True) == 0:
            process.run(params["del_user_cmd"] % user_name)
        process.run(params["add_user_cmd"] % user_name)

        # config socket
        sock_path = os.path.join(
            "/home/" + user_name,
            "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock")),
        )
        # create the socket file before daemon running
        open(sock_path, "w")
        params["fs_source_user_sock_path"] = sock_path

        # create the share folder
        fs_source = params.get("fs_source_dir")
        shared_dir = os.path.join("/home/" + user_name, fs_source)
        if not os.path.exists(shared_dir):
            process.system(
                "runuser -l " + user_name + " -c 'mkdir -p " + shared_dir + "'"
            )

        # give 'x' permission to common user home dir and give share dir
        # write permission for all the users.
        cmd_give_exec_perm = params["cmd_give_exec_perm"] % "/home/" + user_name
        cmd_give_write_perm = params["cmd_give_write_perm"] % shared_dir
        process.run(cmd_give_exec_perm)
        process.run(cmd_give_write_perm)

        # get host_uid/host_gid and count
        uid_begin, uid_count = get_sub_uid_gid("subuid")
        gid_begin, gid_count = get_sub_uid_gid("subgid")
        fsd_map_option = params["fs_binary_extra_options"]

        # start virtiofsd
        if map_type == "one_to_one":
            fs_binary_extra_options = fsd_map_option % (uid_begin, gid_begin)
        else:
            fs_binary_extra_options = fsd_map_option % (
                uid_begin,
                uid_count,
                gid_begin,
                gid_count,
            )
        cmd_run_virtiofsd = params["cmd_run_virtiofsd"] % sock_path
        cmd_run_virtiofsd += " --shared-dir %s" % shared_dir
        cmd_run_virtiofsd += fs_binary_extra_options
        error_context.context(
            "Running daemon command %s with %s user." % (cmd_run_virtiofsd, user_name),
            test.log.info,
        )
        p_vfsd = aexpect.ShellSession(
            "runuser -l " + user_name + " -c '" + cmd_run_virtiofsd + "'",
            auto_close=False,
            output_func=utils_misc.log_line,
            output_params=(vfsd_log_name,),
            prompt=r"^\[.*\][\#\$]\s*$",
        )
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()

        if not utils_misc.make_dirs(fs_dest, session):
            test.fail("Creating directory was failed!")
        error_context.context(
            "Mount virtiofs target %s to %s inside" " guest." % (fs_target, fs_dest),
            test.log.info,
        )
        if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
            test.fail("Mount virtiofs target failed.")

        for guest_user in ["root", common_guest_user]:
            # create a new file in guest.
            file_name = create_file_in_guest(guest_user)
            # if map type is 1 to 1, then create file will fail with
            # a common user, so there is no need to check the uid/gid
            if not (map_type == "one_to_one" and guest_user == common_guest_user):
                uid_gid_guest = get_file_owner_id_guest(file_name)
                uid_gid_host = get_file_owner_id_host(file_name)
                expect_id = get_expect_user_id(guest_user)
                msg = "The new file's uid:gid is wrong from %s\n"
                msg += "expect one is %s\nthe real one is %s."
                if uid_gid_guest != expect_id["guest"]:
                    test.fail(msg % ("guest", expect_id["guest"], uid_gid_guest))
                if uid_gid_host != expect_id["host"]:
                    test.fail(msg % ("host", expect_id["host"], uid_gid_host))
    finally:
        error_context.context("Clean the env, delete the user on guest.", test.log.info)
        utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
        utils_misc.safe_rmdir(fs_dest, session=session)
        if session.cmd_status("id %s" % common_guest_user) == 0:
            session.cmd(del_user_cmd % common_guest_user)
        if vm and vm.is_alive():
            vm.destroy()
        error_context.context("Delete the user on host.", test.log.info)
        if p_vfsd:
            p_vfsd.kill()
        process.run(del_user_cmd % user_name)
