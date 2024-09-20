"""Check memory leak on block devices"""

import os
import re
import time

from avocado.utils import process
from virttest import arch, error_context
from virttest import data_dir as virttest_data_dir
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Check memory leak on block devices test

    1) Using valgrind to boot the main vm with multi disks.
    2) Execute IO on multi disks
    3) Wait the IO doing in minutes.
    4) Destroy the VM.
    5) Check leak info in valgrind log .


    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _execute_io_in_guest():
        devs = ""
        for serial in data_images:
            drive = get_linux_drive_path(session, serial)
            if drive:
                devs += drive.replace("/dev/", "") + " "

        guest_io_cmd = params["guest_io_cmd"] % devs
        host_script = params["host_script"]
        guest_dir = params["guest_dir"]
        deps_dir = virttest_data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, host_script)
        vm.copy_files_to(host_file, guest_dir)
        logger.info("Execute io:%s", guest_io_cmd)
        session.sendline("$SHELL " + guest_io_cmd)

    if arch.ARCH in ("ppc64", "ppc64le"):
        output = process.system_output("lscfg --list firmware -v", shell=True).decode()
        ver = float(re.findall(r"\d\.\d", output)[0])
        if ver >= 6.3:
            # bz2235228,cancel test due to known product bug.
            test.cancel(
                "Skip test for xive kvm interrupt guest due to"
                " known host crash issue."
            )
    logger = test.log
    data_images = params["data_images"].split()
    error_context.context("Get the main VM", logger.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = params.get_numeric("login_timeout", 360)
    session = vm.wait_for_login(timeout=timeout)
    time.sleep(60)
    logger.info("Start to IO in guest")
    _execute_io_in_guest()
    logger.info("Wait ...")
    time.sleep(params.get_numeric("io_timeout", 300))

    logger.info("Try to cancel IO.")
    session = vm.wait_for_login(timeout=timeout)
    session.cmd(params["guest_cancel_io_cmd"], timeout=timeout)
    logger.info("Ready to destroy vm")
    vm.destroy()
    logger.info("Ready to check vm...")
    cp_cmd = "cp %s %s" % (params["valgrind_log"], test.logdir)
    process.system_output(cp_cmd, shell=True)
    check_cmd = params["check_cmd"]
    out = process.system_output(check_cmd, shell=True).decode()
    leak_threshold = params.get_numeric("leak_threshold")
    logger.info("Find leak:%s,threshold: %d", out, leak_threshold)
    if len(out) and int(out) > leak_threshold:
        test.fail("Find memory leak %s,Please check valgrind.log" % out)
