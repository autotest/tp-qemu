import os

import aexpect
from avocado.utils import process
from virttest import env_process, error_context, nfs, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils, win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Start virtiofsd with the user who has permission to access the directory
    of another user, then test whether the shared directory works well or not.

    1) Create two users( e.g. u1 and u2) on host.
    2) Change permission of u1 home directory, give all write permission.
    3) Change user u2's supplementary group to u1.
    4) Start virtiofsd under user u2
       with the option "--shared-dir /home/u1/virtio_fs_test".
    5) Boot a guest on the host.
    6) If guest is windows, start the viofs service and reboot.
    7) If the guest is linux, mount the file system.
    8) Run the basic io test and folder accessing test.
    9) After test, clear the environment.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    add_user_cmd = params.get("add_user_cmd")
    del_user_cmd = params.get("del_user_cmd")
    username = params.objects("new_user")
    windows = params.get("os_type", "windows") == "windows"
    driver_name = params.get("driver_name")
    fs_dest = params.get("fs_dest")
    fs_target = params.get("fs_target")
    cmd_run_virtiofsd = params.get("cmd_run_virtiofsd")

    # nfs config
    setup_local_nfs = params.get("setup_local_nfs")

    fs_source = params.get("fs_source_dir")
    guest_session = None
    vm = None
    nfs_local = None

    try:
        for _username in username:
            add_cmd = add_user_cmd % _username
            if process.system("id %s" % _username, shell=True, ignore_status=True) == 0:
                s, o = process.getstatusoutput(del_user_cmd % _username)
                if s:
                    if "is currently used by process" in o:
                        test.error(
                            "The common user is used by other process,"
                            " pls check on your host."
                        )
                    else:
                        test.fail("Unknown error when deleting the " "user: %s" % o)
            if (
                process.system(
                    "grep %s /etc/group" % _username, shell=True, ignore_status=True
                )
                == 0
            ):
                add_cmd = "useradd -g %s %s" % (_username, _username)
            process.run(add_cmd)
        user_one, user_two = username[0], username[-1]
        # create the folder before daemon running
        shared_dir = os.path.join("/home/" + user_one, fs_source)
        if not os.path.exists(shared_dir):
            process.system(
                "runuser -l " + user_one + " -c 'mkdir -p " + shared_dir + "'"
            )

        if setup_local_nfs:
            # delete the slash at the end
            params["nfs_mount_dir"] = shared_dir[:-1]
            nfs_local = nfs.Nfs(params)
            nfs_local.setup()

        # change permission of u1 home directory
        output = process.system_output("chmod -R 777 /home/%s" % user_one)
        error_context.context(output, test.log.info)
        # change user u2's supplementary group to u1
        output = process.system_output("usermod -G %s %s" % (user_one, user_two))
        error_context.context(output, test.log.info)

        # set fs daemon config
        sock_path = os.path.join(
            "/home/" + user_two, "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock"))
        )
        # create the file
        with open(sock_path, "w"):
            pass
        params["fs_source_user_sock_path"] = sock_path

        # run daemon
        cmd_run_virtiofsd = cmd_run_virtiofsd % sock_path
        cmd_run_virtiofsd += " --shared-dir %s" % shared_dir
        error_context.context(
            "Running daemon command %s" % cmd_run_virtiofsd, test.log.info
        )

        aexpect.ShellSession(
            "runuser -l " + user_two + " -c '" + cmd_run_virtiofsd + "'",
            auto_close=False,
            output_func=utils_misc.log_line,
            output_params=("virtiofs_fs-virtiofs.log",),
            prompt=r"^\[.*\][\#\$]\s*$",
        )
        params["fs_source_base_dir"] = "/home/" + user_one

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        guest_session = vm.wait_for_login()

        if windows:
            guest_session = utils_test.qemu.windrv_check_running_verifier(
                guest_session, vm, test, driver_name
            )
            virtio_fs_utils.run_viofs_service(test, params, guest_session)
        else:
            error_context.context(
                "Create a destination directory %s " "inside guest." % fs_dest,
                test.log.info,
            )
            if not utils_misc.make_dirs(fs_dest, session=guest_session):
                test.fail("Creating directory was failed!")
            error_context.context(
                "Mount virtiofs target %s to %s inside"
                " guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(
                fs_target, fs_dest, "virtiofs", session=guest_session
            ):
                test.fail("Mount virtiofs target failed.")
        virtio_fs_utils.basic_io_test(test, params, guest_session)
    finally:
        if guest_session:
            if windows:
                virtio_fs_utils.delete_viofs_serivce(test, params, guest_session)
                # for windows guest, disable/uninstall driver to get memory leak
                # based on driver verifier is enabled
                win_driver_utils.memory_leak_check(vm, test, params)
            else:
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=guest_session)
                utils_misc.safe_rmdir(fs_dest, session=guest_session)

        if vm and vm.is_alive():
            vm.destroy()
        if setup_local_nfs and nfs_local:
            nfs_local.cleanup()

        error_context.context("Delete the user(s) on host...", test.log.info)
        for _username in username[::-1]:
            output = process.run(del_user_cmd % _username)
            if "is currently used by process" in output.stdout_text:
                error_context.context(
                    "Kill process before delete user...", test.log.info
                )
                pid = output.split(" ")[-1]
                process.run("kill -9 %s" % pid)
            process.run("rm -rf /home/%s" % _username)
