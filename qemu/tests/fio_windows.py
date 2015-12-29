import re
import time
import logging

from virttest import error_context
from virttest import utils_misc

from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    KVM guest stop test:
    1) Log into a guest
    2) Check is fio.msi installed, install it if not installed.
    3) Start fio in guest
    4) Get the result

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    install_path = params["install_path"].rstrip("\\")
    log_file = params.get("log_file")
    fio_cmd = params.get("fio_cmd")
    timeout = float(params.get("login_timeout", 360))
    test_timeout = int(params.get("test_timeout", "360"))
    check_installed_cmd = 'dir "%s"|findstr /I fio' % install_path
    check_installed_cmd = params.get("check_installed_cmd",
                                     check_installed_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    try:
        installed = session.cmd_status(check_installed_cmd) == 0
        if not installed:
            dst = r"%s:\\" % utils_misc.get_winutils_vol(session)

            error_context.context("Install fio in guest", logging.info)
            install_cmd = params["install_cmd"]
            install_cmd = re.sub(r"DRIVE:\\+", dst, install_cmd)
            session.cmd(install_cmd, timeout=180)
            time.sleep(30)
            config_cmd = params.get("config_cmd")
            if config_cmd:
                session.cmd(config_cmd)

        error_context.context("Start fio in guest.", logging.info)
        s, o = session.cmd_status_output(fio_cmd, timeout=(test_timeout+60))
        if s:
            raise exceptions.TestError("Failed to run fio, output: %s") % o

    finally:
        error_context.context("Copy fio log from guest to host.", logging.info)
        vm.copy_files_from(log_file, test.resultsdir)
        if session:
            session.close()
