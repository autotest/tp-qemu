import re

from virttest import error_context
from virttest.virt_vm import VMCreateError


@error_context.context_aware
def run(test, params, env):
    """
    qemu should be terminated when launching an L1 guest with
    "cap-nested-hv=on,max-cpu-compat=power8".

    1) Launch a guest with "cap-nested-hv=on,max-cpu-compat=power8".
    2) Check whether qemu terminates.
    3) Check whether the qemu output is as expected.

    :param test: Qemu test object.
    :param params: the test params.
    :param env: test environment.
    """

    params["start_vm"] = "yes"
    error_msg = params["error_msg"]
    vm = env.get_vm(params["main_vm"])

    error_context.base_context("Try to create a qemu instance...", test.log.info)
    try:
        vm.create(params=params)
    except VMCreateError as e:
        if not re.search(error_msg, e.output):
            test.log.error(e.output)
            test.error("The error message could not be searched at qemu " "outputs.")
        test.log.info("qemu terminated with the expected error message.")
    else:
        test.fail(
            "The qemu instance should not be launched with "
            '"cap-nested-hv=on" and "max-cpu-compat=power8".'
        )
