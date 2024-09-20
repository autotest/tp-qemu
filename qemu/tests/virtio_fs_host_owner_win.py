import os
import random
import re
import string
import time

import aexpect
from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_test
from virttest.qemu_devices import qdevices

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs by sharing the data between host and guest.
    Steps:
        1. Create shared directories on the host.
        2. Create a common user on host.
        3. Start virtiofs daemon with root or the common user.
        4. Change the shared directory's owner to a common user 'test' and give
        all permission to other users.
        5. Boot a guest with virtiofs options.
        6. Log into guest and start virtiofs service.
        7. Edit the registry to set the owner value and restart virtiofs service.
        8. Create a file on the shared dir in guest.
        9. Check the file from host side to check the file's UID/GID.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_user_uid_gid(user_name):
        """
        Get user's UID and GID on host.
        """
        output = process.system_output("id %s" % user_name, shell=True).decode().strip()
        pattern = r"uid=(\d*).*gid=(\d*)"
        match_string = re.findall(pattern, output)
        uid_user = match_string[0][0]
        gid_user = match_string[0][1]
        return uid_user + ":" + gid_user

    def enable_uid_gid(uid_gid_value):
        """
        Enable UID:GID argument to virtiofs service.
        """
        enable_cmd = params["viofs_owner_enable_cmd"] % uid_gid_value
        s, o = session.cmd_status_output(enable_cmd)
        if s:
            test.fail("Fail command: %s. Output: %s." % (enable_cmd, o))
        error_context.context(
            "Restart virtiofs service after modify" " the registry.", test.log.info
        )
        virtio_fs_utils.stop_viofs_service(test, params, session)
        virtio_fs_utils.start_viofs_service(test, params, session)
        time.sleep(1)

    def check_file_uid_gid(volume_letter, shared_dir, expect_id):
        """
        Check file UID and GID on host.
        """
        error_context.context("Create a file in shared dir.", test.log.info)
        file_name = "file_" + "".join(
            random.sample(string.ascii_letters + string.digits, 3)
        )
        guest_file = volume_letter + ":\\" + file_name
        session.cmd(create_file_cmd % guest_file, io_timeout)
        error_context.context("Check the file's UID and GID on host.", test.log.info)
        host_file = os.path.join(shared_dir, file_name)
        output = (
            process.system_output("ls -l %s" % host_file, shell=True).decode().strip()
        )
        owner = output.split()[2]
        group = output.split()[3]
        if process.system("id %s -u" % owner, shell=True, ignore_status=True):
            uid = owner
        else:
            uid = process.system_output("id %s -u" % owner, shell=True).decode().strip()
        if process.system("id %s -g" % group, shell=True, ignore_status=True):
            gid = group
        else:
            gid = process.system_output("id %s -g" % group, shell=True).decode().strip()
        uid_gid_host = uid + ":" + gid
        if uid_gid_host != expect_id:
            test.fail(
                "Check file owner/group failed, "
                "real value is %s, "
                "expected value is %s" % (uid_gid_host, expect_id)
            )

    fs_target = params.get("fs_target")
    create_file_cmd = params.get("create_file_cmd")
    io_timeout = params.get_numeric("cmd_timeout", 120)

    if params.get("privileged", "") == "no":
        # start virtiofsd with user config
        user_name = params["new_user"]
        add_user_cmd = params["add_user_cmd"]
        del_user_cmd = params["del_user_cmd"]
        if process.system("id %s" % user_name, shell=True, ignore_status=True) == 0:
            s, o = process.getstatusoutput(del_user_cmd)
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
                "grep %s /etc/group" % user_name, shell=True, ignore_status=True
            )
            == 0
        ):
            add_user_cmd = "useradd -g %s %s" % (user_name, user_name)
        process.run(add_user_cmd)

        # config socket
        sock_path = os.path.join(
            "/home/" + user_name,
            "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock")),
        )
        # create the socket file before daemon running
        with open(sock_path, "w"):
            pass
        params["fs_source_user_sock_path"] = sock_path

        # create the folder
        fs_source = params.get("fs_source_dir")
        shared_dir = os.path.join("/home/" + user_name, fs_source)
        if not os.path.exists(shared_dir):
            process.system(
                "runuser -l " + user_name + " -c 'mkdir -p " + shared_dir + "'"
            )

        # start daemon with a common user
        cmd_run_virtiofsd = params["cmd_run_virtiofsd"] % sock_path
        cmd_run_virtiofsd += " --shared-dir %s" % shared_dir
        error_context.context(
            "Running daemon command %s with %s user." % (cmd_run_virtiofsd, user_name),
            test.log.info,
        )

        aexpect.ShellSession(
            "runuser -l " + user_name + " -c '" + cmd_run_virtiofsd + "'",
            auto_close=False,
            output_func=utils_misc.log_line,
            output_params=("virtiofs_fs-virtiofs.log",),
            prompt=r"^\[.*\][\#\$]\s*$",
        )
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context(
        "Change the shared dir's owner and group" " to 'test' on host.", test.log.info
    )
    if params.get("privileged", "") == "yes":
        # get shared dir by qdevices.
        shared_dir = None
        for device in vm.devices:
            if isinstance(device, qdevices.QVirtioFSDev):
                shared_dir = device.get_param("source")

    change_source_owner = params["change_source_owner"] % shared_dir
    process.run(change_source_owner)
    # add all permission to others
    change_source_perm = params["change_source_perm"] % shared_dir
    process.run(change_source_perm)

    # Check whether windows driver is running,and enable driver verifier
    driver_name = params["driver_name"]
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_name
    )
    virtio_fs_utils.run_viofs_service(test, params, session)

    # get shared volume letter
    volume_letter = virtio_fs_utils.get_virtiofs_driver_letter(test, fs_target, session)
    # set matching table for test uid:gid and expected uid:gid.
    if params.get("privileged", "") == "yes":
        uid_gid_test_user = get_user_uid_gid("test")
        dict_ids = {
            "null": uid_gid_test_user,
            "0:0": "0:0",
            "11111:11111": "11111:11111",
        }
    else:
        uid_gid_new_user = get_user_uid_gid(user_name)
        dict_ids = {
            "null": uid_gid_new_user,
            "0:0": uid_gid_new_user,
            uid_gid_new_user: uid_gid_new_user,
        }
    # set UID/GID to virtiofs service and check the created file on host.
    for test_value, expect_value in dict_ids.items():
        error_context.context(
            "Set host UID:GID=%s to viofs" " service." % test_value, test.log.info
        )
        s, o = session.cmd_status_output(params["viofs_owner_query_cmd"])
        if s == 0:
            test.log.info("Delete owner key and value from registry.")
            session.cmd(params["viofs_owner_delete_cmd"])
            virtio_fs_utils.stop_viofs_service(test, params, session)
            virtio_fs_utils.start_viofs_service(test, params, session)
            time.sleep(1)
        if test_value != "null":
            enable_uid_gid(test_value)
        check_file_uid_gid(volume_letter, shared_dir, expect_value)
