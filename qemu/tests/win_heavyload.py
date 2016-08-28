import re
import logging
import time

try:
    import aexpect
except ImportError:
    from virttest import aexpect

from autotest.client.shared import error
from autotest.client import utils

from virttest import utils_misc
from virttest import data_dir


@error.context_aware
def run(test, params, env):
    """
    KVM guest stop test:
    1) Log into a guest
    2) Check is HeavyLoad.exe installed , download and
       install it if not installed.
    3) Start Heavyload to make guest in heavyload
    4) Check vm is alive
    5) Stop heavyload process and clean temp file.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def loop_session_cmd(session, cmd):
        def session_cmd(session, cmd):
            try:
                return session.cmd_status(cmd) == 0
            except (aexpect.ShellStatusError, aexpect.ShellTimeoutError):
                pass

        count = 0
        while count < 3:
            ret = session_cmd(session, cmd)
            if ret is not None:
                return ret
            count += 1
        return None

    def add_option(cmd, key, val):
        """
        Append options into command;
        """
        if re.match(r".*/%s.*", cmd, re.I):
            if val:
                rex = r"/%s\b+\S+\b+" % key
                val = "/%s %s " % (key, val)
                cmd = re.sub(rex, val, cmd, re.I)
        else:
            cmd += " /%s %s " % (key, val)
        return cmd

    tmp_dir = data_dir.get_tmp_dir()
    install_path = params["install_path"].rstrip("\\")
    heavyload_bin = '"%s\heavyload.exe"' % install_path
    start_cmd = "%s /CPU /MEMORY /FILE " % heavyload_bin
    stop_cmd = "taskkill /T /F /IM heavyload.exe"
    stop_cmd = params.get("stop_cmd", stop_cmd)
    start_cmd = params.get("start_cmd", start_cmd)
    check_running_cmd = "tasklist|findstr /I heavyload"
    check_running_cmd = params.get("check_running_cmd", check_running_cmd)
    test_installed_cmd = "dir '%s'|findstr /I heavyload" % install_path
    test_installed_cmd = params.get("check_installed_cmd", test_installed_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    try:
        installed = session.cmd_status(test_installed_cmd) == 0
        if not installed:
            download_url = params.get("download_url")
            if download_url:
                dst = r"c:\\"
                pkg_md5sum = params["pkg_md5sum"]
                error.context("Download HeavyLoadSetup.exe", logging.info)
                pkg = utils.unmap_url_cache(tmp_dir,
                                            download_url, pkg_md5sum)
                vm.copy_files_to(pkg, dst)
            else:
                dst = r"%s:\\" % utils_misc.get_winutils_vol(session)

            error.context("Install HeavyLoad in guest", logging.info)
            install_cmd = params["install_cmd"]
            install_cmd = re.sub(r"DRIVE:\\+", dst, install_cmd)
            session.cmd(install_cmd)
            config_cmd = params.get("config_cmd")
            if config_cmd:
                session.cmd(config_cmd)

        error.context("Start heavyload in guest", logging.info)
        # genery heavyload command automaticly
        if params.get("autostress") == "yes":
            free_mem = utils_misc.get_free_mem(session, "windows")
            free_disk = utils_misc.get_free_disk(session, "C:")
            start_cmd = '"%s\heavyload.exe"' % params["install_path"]
            start_cmd = add_option(start_cmd, 'CPU', params["smp"])
            start_cmd = add_option(start_cmd, 'MEMORY', free_mem)
            start_cmd = add_option(start_cmd, 'FILE', free_disk)
        else:
            start_cmd = params["start_cmd"]
        # reformat command to ensure heavyload started as except
        test_timeout = int(params.get("timeout", "60"))
        steping = 60
        if test_timeout < 60:
            logging.warn("Heavyload use minis as unit of timeout,"
                         "values is too small, use default: 60s")
            test_timeout = 60
            steping = 30
        test_timeout = test_timeout / 60
        start_cmd = add_option(start_cmd, 'DURATION', test_timeout)
        start_cmd = add_option(start_cmd, 'START', '')
        start_cmd = add_option(start_cmd, 'AUTOEXIT', '')
        logging.info("heavyload cmd: %s" % start_cmd)
        session.sendline(start_cmd)
        if not loop_session_cmd(session, check_running_cmd):
            raise error.TestError("heavyload process is not started")

        sleep_before_migration = int(params.get("sleep_before_migration",
                                                "0"))
        time.sleep(sleep_before_migration)

        error.context("Verify vm is alive", logging.info)
        utils_misc.wait_for(vm.verify_alive,
                            timeout=test_timeout, step=steping)
    finally:
        # in migration test, no need to stop heavyload on src host
        cleanup_in_the_end = params.get("unload_stress_in_the_end", "yes")
        if cleanup_in_the_end == "yes":
            error.context("Stop load and clean tmp files", logging.info)
            if not installed and download_url:
                utils.system("rm -f %s/HeavyLoad*.exe" % tmp_dir)
                session.cmd("del /f /s %sHeavyLoad*.exe" % dst)
            if loop_session_cmd(session, check_running_cmd):
                if not loop_session_cmd(session, stop_cmd):
                    raise error.TestFail("Unable to terminate heavyload "
                                         "process")
        if session:
            session.close()
