import os
import shutil

import aexpect
from avocado.utils import process
from virttest import env_process, error_context, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils, win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Virtiofs works on sandbox is none.
     Steps:
        1. create a common user u1.
        2. switch to this user and create a shared dir in the home directory
        3. start virtiofsd process with user u1.
        4. Boot a guest on the host with virtiofs options.
        5. Log into guest then mount the virtiofs targets.
        6. Generate files or run stress on the mount points inside guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    common_user = params["common_user"]
    error_context.context("Create an common user.", test.log.info)
    process.system(params["del_user_cmd"], ignore_status=True, shell=True)
    process.system(params["add_user_cmd"], shell=True)

    error_context.context(
        "Switch to the common user and create the" " shared dir in home dir.",
        test.log.info,
    )
    # set fs shared dir
    shared_dir = "/home/" + common_user + "/virtio_fs_test"
    params["fs_source_dir"] = shared_dir

    # set fs daemon path
    if os.path.exists(shared_dir):
        shutil.rmtree(shared_dir, ignore_errors=True)
    process.system("su - %s -c 'mkdir -p %s'" % (common_user, shared_dir), shell=True)

    # set fs socket
    sock_path = os.path.join(
        "/home/" + common_user, "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock"))
    )
    params["fs_source_user_sock_path"] = sock_path

    # run daemon
    cmd_run_virtiofsd = params["cmd_run_virtiofsd"] % (sock_path, shared_dir)
    cmd_run_virtiofsd += params.get("fs_binary_extra_options")
    error_context.context(
        "Running daemon command %s with user." % cmd_run_virtiofsd, test.log.info
    )

    virtiofsd_cmd = "runuser -l %s -c '%s'" % (common_user, cmd_run_virtiofsd)
    session = aexpect.ShellSession(
        virtiofsd_cmd,
        auto_close=False,
        output_func=utils_misc.log_line,
        output_params=("virtiofs_fs-virtiofs.log",),
        prompt=r"^\[.*\][\#\$]\s*$",
    )
    # start vm
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    is_windows = params.get("os_type") == "windows"
    session = vm.wait_for_login()

    try:
        if is_windows:
            cmd_timeout = params.get_numeric("cmd_timeout", 120)
            driver_name = params["driver_name"]
            # Check whether windows driver is running,and enable driver verifier
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name
            )
            # create virtiofs service
            viofs_svc_name = params["viofs_svc_name"]
            virtio_fs_utils.create_viofs_service(
                test, params, session, service=viofs_svc_name
            )

        fs_target = params["fs_target"]
        fs_dest = params["fs_dest"]
        if not is_windows:
            # mount virtiofs
            error_context.context(
                "Create a destination directory %s " "inside guest." % fs_dest,
                test.log.info,
            )
            utils_misc.make_dirs(fs_dest, session)
            error_context.context(
                "Mount virtiofs target %s to %s inside"
                " guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                test.fail("Mount virtiofs target failed.")

            # can't change file's owner and group
            test_file = "%s/test" % fs_dest
            session.cmd("echo aaa > %s" % test_file)
            s, o = session.cmd_status_output("chgrp root %s" % test_file)
            if not s:
                test.fail(
                    "Should not change file's owner/group because"
                    " it's unprivileged, the output is %s" % o
                )
        else:
            # start virtiofs
            error_context.context("Start virtiofs service in guest.", test.log.info)
            virtio_fs_utils.start_viofs_service(test, params, session)

            # get fs dest for vm
            virtio_fs_disk_label = fs_target
            error_context.context(
                "Get Volume letter of virtio fs target, the disk"
                "lable is %s." % virtio_fs_disk_label,
                test.log.info,
            )
            vol_con = "VolumeName='%s'" % virtio_fs_disk_label
            volume_letter = utils_misc.wait_for(
                lambda: utils_misc.get_win_disk_vol(session, condition=vol_con),
                cmd_timeout,  # pylint: disable=E0606
            )
            if volume_letter is None:
                test.fail("Could not get virtio-fs mounted volume letter.")
            fs_dest = "%s:" % volume_letter

        # basic io test
        virtio_fs_utils.basic_io_test(test, params, session)
    finally:
        if is_windows:
            virtio_fs_utils.delete_viofs_serivce(test, params, session)
            # for windows guest, disable/uninstall driver to get memory leak based on
            # driver verifier is enabled
            win_driver_utils.memory_leak_check(vm, test, params)
        else:
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
        if vm and vm.is_alive():
            vm.destroy()
            process.system(params["del_user_cmd"], ignore_status=True, shell=True)
