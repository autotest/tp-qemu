import re
import time

import aexpect
from avocado.utils import process
from virttest import error_context, utils_misc, utils_test
from virttest.utils_windows import system

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Qemu virtio-rng device test:
    1) boot guest with virtio-rng device
    3) check host random device opened by qemu (optional)
    4) enable driver verifier in guest
    5) check device using right driver in guest.
    6) read random data from guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def is_dev_used_by_qemu(dev_file, vm_pid):
        """
        Check host random device opened by qemu.

        :param dev_file: host random device name.
        :param vm_pid: qemu process ID.
        :return: Match objects or None.
        """
        lsof_cmd = "lsof %s" % dev_file
        output = process.system_output(lsof_cmd, ignore_status=True).decode()
        return re.search(r"\s+%s\s+" % vm_pid, output, re.M)

    def _is_rngd_running():
        """
        Check whether rngd is running
        """
        output = session.cmd_output(check_rngd_service)  # pylint: disable=E0606
        if "running" not in output:
            return False
        return True

    rng_data_rex = params.get("rng_data_rex", r".*")
    dev_file = params.get("filename_passthrough")
    timeout = float(params.get("login_timeout", 360))
    rng_dll_register_cmd = params.get("rng_dll_register_cmd")
    read_rng_timeout = float(params.get("read_rng_timeout", "360"))
    cmd_timeout = float(params.get("session_cmd_timeout", "360"))
    rng_src = params.get("rng_src", "WIN_UTILS:\\random_%PROCESSOR_ARCHITECTURE%.exe")
    driver_name = params["driver_name"]
    read_rng_cmd = params["read_rng_cmd"]
    rng_dst = params.get("rng_dst", "c:\\random_%PROCESSOR_ARCHITECTURE%.exe")
    os_type = params["os_type"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm_pid = vm.get_pid()

    if dev_file:
        error_context.context("Check '%s' used by qemu" % dev_file, test.log.info)
        if not is_dev_used_by_qemu(dev_file, vm_pid):
            msg = "Qemu (pid=%d) not using host passthrough " % vm_pid
            msg += "device '%s'" % dev_file
            test.fail(msg)
    session = vm.wait_for_login(timeout=timeout)

    if os_type == "windows":
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )
        if not system.file_exists(session, rng_dst):
            rng_src = utils_misc.set_winutils_letter(session, rng_src)
            session.cmd("copy %s %s /y" % (rng_src, rng_dst))
    else:
        update_driver = params.get("update_driver")
        if update_driver:
            session.cmd(update_driver, timeout=cmd_timeout)
        error_context.context("verify virtio-rng device driver", test.log.info)
        verify_cmd = params["driver_verifier_cmd"]
        try:
            output = session.cmd_output_safe(verify_cmd, timeout=cmd_timeout)
        except aexpect.ShellTimeoutError:
            err = "%s timeout, pls check if it's a product bug" % verify_cmd
            test.fail(err)

        if not re.search(r"%s" % driver_name, output, re.M):
            msg = "Verify device driver failed, "
            msg += "guest report driver is %s, " % output
            msg += "expect is '%s'" % driver_name
            test.fail(msg)

    error_context.context("Read virtio-rng device to get random number", test.log.info)

    if rng_dll_register_cmd:
        test.log.info("register 'viorngum.dll' into system")
        session.cmd(rng_dll_register_cmd, timeout=120)

    if os_type == "linux":
        check_rngd_service = params.get("check_rngd_service")
        if check_rngd_service:
            if not utils_misc.wait_for(_is_rngd_running, 30, first=5):
                start_rngd_service = params["start_rngd_service"]
                status, output = session.cmd_status_output(start_rngd_service)
                if status:
                    test.error(output)

    if params.get("test_duration"):
        start_time = time.time()
        while (time.time() - start_time) < float(params.get("test_duration")):
            output = session.cmd_output(read_rng_cmd, timeout=read_rng_timeout)
            if len(re.findall(rng_data_rex, output, re.M)) < 2:
                test.fail("Unable to read random numbers from guest: %s" % output)
    else:
        output = session.cmd_output(read_rng_cmd, timeout=read_rng_timeout)
        if len(re.findall(rng_data_rex, output, re.M)) < 2:
            test.fail("Unable to read random numbers from guest: %s" % output)
    session.close()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("need_memory_leak_check", "no") == "yes":
        win_driver_utils.memory_leak_check(vm, test, params)
