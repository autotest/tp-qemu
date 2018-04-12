import logging

from virttest import virt_vm
from virttest import utils_net
from virttest import env_process


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
        logging.debug("VM Failed to create. This was expected. Reason:\n%s",
                      str(err))
    else:
        raise VMCreateSuccess()
