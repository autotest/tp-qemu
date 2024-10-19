import os
import re
import time

import aexpect
from avocado.utils import download
from virttest import data_dir, error_context, utils_misc


@error_context.context_aware
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
    heavyload_bin = r'"%s\heavyload.exe"' % install_path
    start_cmd = "%s /CPU /MEMORY /FILE " % heavyload_bin
    stop_cmd = "taskkill /T /F /IM heavyload.exe"
    stop_cmd = params.get("stop_cmd", stop_cmd)
    start_cmd = params.get("start_cmd", start_cmd)
    check_running_cmd = "tasklist|findstr /I heavyload"
    check_running_cmd = params.get("check_running_cmd", check_running_cmd)
    test_installed_cmd = 'dir "%s"|findstr /I heavyload' % install_path
    test_installed_cmd = params.get("check_installed_cmd", test_installed_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    installed = session.cmd_status(test_installed_cmd) == 0
    if not installed:
        download_url = params.get("download_url")
        if download_url:
            dst = r"c:\\"
            pkg_md5sum = params["pkg_md5sum"]
            error_context.context("Download HeavyLoadSetup.exe", test.log.info)
            pkg_name = os.path.basename(download_url)
            pkg_path = os.path.join(tmp_dir, pkg_name)
            download.get_file(download_url, pkg_path, hash_expected=pkg_md5sum)
            vm.copy_files_to(pkg_path, dst)
        else:
            dst = r"%s:\\" % utils_misc.get_winutils_vol(session)

        error_context.context("Install HeavyLoad in guest", test.log.info)
        install_cmd = params["install_cmd"]
        install_cmd = re.sub(r"DRIVE:\\+", dst, install_cmd)
        session.cmd(install_cmd)
        config_cmd = params.get("config_cmd")
        if config_cmd:
            session.cmd(config_cmd)

    error_context.context("Start heavyload in guest", test.log.info)
    # genery heavyload command automaticly
    if params.get("autostress") == "yes":
        free_mem = utils_misc.get_free_mem(session, "windows")
        free_disk = utils_misc.get_free_disk(session, "C:")
        start_cmd = r'"%s\heavyload.exe"' % params["install_path"]
        start_cmd = add_option(start_cmd, "CPU", vm.cpuinfo.smp)
        start_cmd = add_option(start_cmd, "MEMORY", free_mem)
        start_cmd = add_option(start_cmd, "FILE", free_disk)
    else:
        start_cmd = params["start_cmd"]
    # reformat command to ensure heavyload started as except
    test_timeout = int(params.get("timeout", "60"))
    steping = 60
    if test_timeout < 60:
        test.log.warning(
            "Heavyload use mins as unit of timeout, given timeout "
            "is too small (%ss), force set to 60s",
            test_timeout,
        )
        test_timeout = 60
        steping = 30
    start_cmd = add_option(start_cmd, "DURATION", test_timeout / 60)
    start_cmd = add_option(start_cmd, "START", "")
    start_cmd = add_option(start_cmd, "AUTOEXIT", "")
    test.log.info("heavyload cmd: %s", start_cmd)
    session.sendline(start_cmd)
    if not loop_session_cmd(session, check_running_cmd):
        test.error("heavyload process is not started")

    sleep_before_migration = int(params.get("sleep_before_migration", "0"))
    time.sleep(sleep_before_migration)

    error_context.context("Verify vm is alive", test.log.info)
    utils_misc.wait_for(vm.verify_alive, timeout=test_timeout * 1.2, step=steping)

    if not session.cmd_status(check_running_cmd):
        test.fail("heavyload doesn't exist normally")
    if session:
        session.close()
