import re

from virttest import env_process, utils_net, virt_vm


class VMCreateSuccess(Exception):
    def __str__(self):
        return "VM succeeded to create. This was not expected"


def run(test, params, env):
    """
    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    :raise VMCreateSuccess: in case that vm.create() passed

    This test is designed to check if qemu exits on passed invalid
    argument values.

    E.g. -spice port=-1 or -spice port=hello
    """

    try:
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])
    except (virt_vm.VMError, utils_net.NetError) as err:
        message = str(err)
        test.log.debug("VM Failed to create. This was expected. Reason:\n%s", message)

        error_msg = params.get("error_msg")
        if error_msg and not re.search(error_msg, message, re.M | re.I):
            test.fail("Can't find the expected error message: %s", error_msg)
    else:
        raise VMCreateSuccess()
