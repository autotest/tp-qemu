import re
import time

from virttest import error_context, utils_misc

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    KVM guest stop test:
    1) Log into a guest
    2) Check is fio.msi installed, install it if not installed.
    3) Start fio test on both sys and data disk in guest
    4) Get the result

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    install_path = params["install_path"].rstrip("\\")
    fio_log_file = params.get("fio_log_file")
    fio_cmd = params.get("fio_cmd")
    timeout = float(params.get("login_timeout", 360))
    cmd_timeout = int(params.get("cmd_timeout", "360"))
    check_installed_cmd = 'dir "%s/fio"|findstr /I fio.exe' % install_path
    check_installed_cmd = params.get("check_installed_cmd", check_installed_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    if not params.get("image_backend") == "nvme_direct":
        error_context.context("Format disk", test.log.info)
        utils_misc.format_windows_disk(
            session, params["disk_index"], mountpoint=params["disk_letter"]
        )
    try:
        installed = session.cmd_status(check_installed_cmd) == 0
        if not installed:
            dst = r"%s:\\" % utils_misc.get_winutils_vol(session)

            error_context.context("Install fio in guest", test.log.info)
            install_cmd = params["install_cmd"]
            install_cmd = re.sub(r"DRIVE:\\+", dst, install_cmd)
            session.cmd(install_cmd, timeout=180)
            time.sleep(30)
            config_cmd = params.get("config_cmd")
            if config_cmd:
                session.cmd(config_cmd)

        error_context.context("Start fio in guest.", test.log.info)
        status, output = session.cmd_status_output(fio_cmd, timeout=(cmd_timeout * 2))
        if status:
            test.error("Failed to run fio, output: %s" % output)

    finally:
        error_context.context("Copy fio log from guest to host.", test.log.info)
        try:
            vm.copy_files_from(fio_log_file, test.resultsdir)
        except Exception as err:
            test.log.warning("Log file copy failed: %s", err)
        if session:
            session.close()
        win_driver_utils.memory_leak_check(vm, test, params)
