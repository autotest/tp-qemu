import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Check the TSEG default size:
    1) Boot up a guest and the the TSEG size in edk2 log

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def tseg_check(tseg_text):
        """
        Check tseg info, the output like
        QEMU offers an extended TSEG (64 MB) or
        QEMU offers an extended TSEG (16 MB)
        """
        logs = vm.logsessions["seabios"].get_output()
        result = re.search(tseg_text, logs, re.S)
        return result

    tseg_text = params["tseg_text"]
    timeout = params.get_numeric("timeout")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    if not utils_misc.wait_for(
        lambda: tseg_check(tseg_text), timeout, ignore_errors=True
    ):
        test.fail("Does not get expected tseg size from bios log.")
