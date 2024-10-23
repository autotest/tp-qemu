import re
import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Qemu edk2 basic test:
    1) Try to log into a guest
    2) Check serial log information
    3) Check edk2 output information
    4) Add iommu test scenario
    5) Cycle the above process

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    timeout = params.get_numeric("login_timeout", 240)
    line_numbers = params.get_numeric("line_numbers", 40)
    check_messgae = params.get("check_messgae")
    vm = env.get_vm(params["main_vm"])

    for i in range(params.get_numeric("reboot_count", 1)):
        vm.create()
        error_context.context("Check serial log result", test.log.info)
        try:
            output = vm.serial_console.read_until_output_matches(
                [check_messgae], timeout=timeout
            )
        except Exception as msg:
            test.log.error(msg)
            test.fail("No highlighted entry was detected " "the boot was abnormal.")
        error_context.context("Check edk2 output information", test.log.info)
        if re.findall("start failed", output[1], re.I | re.M):
            test.fail(
                "edk2 failed to start, " "please check the serial log for details."
            )
        if len(output[1].splitlines()) > line_numbers:
            test.fail("Warning edk2 line count exceeds %d." % line_numbers)
        time.sleep(2)
        vm.destroy(gracefully=False)
