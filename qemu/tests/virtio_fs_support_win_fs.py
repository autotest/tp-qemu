from virttest import error_context, utils_misc, utils_test

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Virtiofs support for file system name specification (windows only).

    1) Before test, backup the image.
    2) Boot guest with virtiofs device.
    3) Install viofs driver.
    4) Create virtiofs service with administrator user and
       enable NTFS filesystem for virtiofs service.
    5) Copy a program like 7z-x64.exe and autoit script to the shared dir.
    6) Create a new user.
    7) login a common user and to install 7-zip with Admin privilege.
    8) After test, restore the image.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    fs_target = params.get("fs_target")
    winutils_pack_path = params.get("executable_package_path")
    autoIt_path = params.get("autoIt_path")
    script_path = params.get("script_path")
    reg_add_username = params.get("reg_add_username")
    reg_add_pwd = params.get("reg_add_pwd")
    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    driver_running = params.get("driver_running", driver_verifier)

    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    utils_test.qemu.windrv_verify_running(session, test, driver_running)
    session = utils_test.qemu.setup_win_driver_verifier(session, driver_verifier, vm)
    error_context.context("Create the viofs service.", test.log.info)
    virtio_fs_utils.create_viofs_service(test, params, session)
    error_context.context("Add NTFS filesystem to virtiofs.", test.log.info)
    reg_add_cmd = params.get("reg_add_cmd")
    session.cmd(reg_add_cmd)
    error_context.context(
        "restart virtiofs service to make the registry change work.", test.log.info
    )
    virtio_fs_utils.stop_viofs_service(test, params, session)
    virtio_fs_utils.start_viofs_service(test, params, session)

    winutils_driver_letter = utils_misc.get_winutils_vol(session)
    shared_driver_letter = virtio_fs_utils.get_virtiofs_driver_letter(
        test, fs_target, session
    )
    winutils_pack_path = winutils_driver_letter + winutils_pack_path
    autoIt_path = winutils_driver_letter + autoIt_path
    script_path = winutils_driver_letter + script_path
    copy_cmd = "xcopy %s %s:\\ /Y" % (winutils_pack_path, shared_driver_letter)
    error_context.context("Copy the executable to shared dir.", test.log.info)
    session.cmd(copy_cmd)

    error_context.context("Create the new user", test.log.info)
    session.cmd(params.get("add_user_cmd"))
    error_context.context(
        "Replace the default username and password with the new user.", test.log.info
    )
    session.cmd(reg_add_username)
    session.cmd(reg_add_pwd)
    error_context.context("Reboot the guest.", test.log.info)
    session = vm.reboot(session)
    error_context.context(
        "Run autoit script to install executable in explorer.", test.log.info
    )
    session.cmd("start /w " + autoIt_path + " " + script_path)
    exe_name = winutils_pack_path.encode("unicode_escape").decode()[4:]
    output = session.cmd_output("tasklist -v | findstr %s" % exe_name)
    test.log.info("The process found: %s", output)
    output_lower = output.lower()
    if "7-zip" in output_lower and "setup" in output_lower:
        test.log.info(
            "Entry the installation windows of the package with "
            "Admin privilege successfully."
        )
    else:
        test.fail(
            "No process detected while installing the "
            "executable package on the shared directory!\n "
            "Related process: %s" % output
        )
