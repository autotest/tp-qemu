import re
import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    vdpa nic PXE test:

    1) Boot up guest from vdpa NIC
    2) Check guest if works well after sleep 240s

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error_context.context("Try to boot from vdpa NIC", test.log.info)
    vm = env.get_vm(params["main_vm"])
    timeout = params.get_numeric("pxe_timeout")
    test.log.info("Waiting %ss", timeout)
    time.sleep(timeout)
    vm.verify_status("running")
    match_str = params["match_string"]
    output = vm.serial_console.get_output()
    if not re.search(match_str, output, re.M | re.I):
        test.fail("Guest can not boot up from pxe boot")
    test.log.info("Guest works well")
