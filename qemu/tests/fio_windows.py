import re
import time
import logging

from virttest import error_context
from virttest import utils_misc


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
    fio_log_file = params.objects("fio_log_file")
    fio_file_name = params.objects("fio_file_name")
    fio_cmd_sys = params.get("fio_cmd") % (fio_file_name[0], "sys", fio_log_file[0])
    fio_cmd_data = params.get("fio_cmd") % (fio_file_name[1], "data", fio_log_file[1])
    timeout = float(params.get("login_timeout", 360))
    cmd_timeout = int(params.get("cmd_timeout", "360"))
    check_installed_cmd = 'dir "%s"|findstr /I fio' % install_path
    check_installed_cmd = params.get("check_installed_cmd",
                                     check_installed_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_sys = vm.wait_for_login(timeout=timeout)
    session_data = vm.wait_for_login(timeout=timeout)

    error_context.context("Format disk", logging.info)
    utils_misc.format_windows_disk(session_sys, params["disk_index"],
                                   mountpoint=params["disk_letter"])
    try:
        installed = session_sys.cmd_status(check_installed_cmd) == 0
        if not installed:
            dst = r"%s:\\" % utils_misc.get_winutils_vol(session_sys)

            error_context.context("Install fio in guest", logging.info)
            install_cmd = params["install_cmd"]
            install_cmd = re.sub(r"DRIVE:\\+", dst, install_cmd)
            session_sys.cmd(install_cmd, timeout=180)
            time.sleep(30)
            config_cmd = params.get("config_cmd")
            if config_cmd:
                session_sys.cmd(config_cmd)

        error_context.context("Start fio in guest.", logging.info)
        # FIXME:Here use the timeout=(cmd_timeout*2)
        # Will determine a better specific calculation later
        fio_thread_data = utils_misc.InterruptedThread(session_data.cmd_status_output,
                                                       (fio_cmd_data, (cmd_timeout*2)))
        fio_thread_data.start()
        status_sys, output_sys = session_sys.cmd_status_output(fio_cmd_sys,
                                                               timeout=(cmd_timeout*2))
        status_data, output_data = fio_thread_data.join()
        if status_sys or status_data:
            test.error("Failed to run fio, output: %s\n%s" % (output_sys, output_data))

    finally:
        error_context.context("Copy fio log from guest to host.", logging.info)
        try:
            vm.copy_files_from(fio_log_file[0], test.resultsdir)
            vm.copy_files_from(fio_log_file[1], test.resultsdir)
        except Exception, err:
            logging.warn("Log file copy failed: %s" % err)
        session_data.close()
        if session_sys:
            session_sys.close()
