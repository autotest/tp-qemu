import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Verify qemu has no error outputs at different stages in the guest life cycle.

    1) Launch a guest.
    2) Check qemu outputs have not error messages.
    3) Reboot guest and check qemu outputs.
    4) Shutdown guest and check qemu outputs.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def check_qemu_output():
        error_context.context("Check qemu outputs.", test.log.info)
        output = vm.process.get_output()
        if re.search(check_pattern, output, re.I):
            test.log.debug("qemu outputs: %s", output)
            test.fail("Error message is captured in qemu output.")
        test.log.info("No error message was found in the qemu output.")

    check_pattern = params["check_pattern"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()
    try:
        check_qemu_output()
        vm.reboot()
        check_qemu_output()
        vm.monitor.system_powerdown()
        check_qemu_output()
    finally:
        vm.destroy()
