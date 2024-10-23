import re

from virttest import error_context, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    hpt guest's negative test:
    1) Boot vm with incorrect hpt_huge_page value options
    2) Check if can get the expected qemu output

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    error_msg = params.get("error_msg")
    try:
        vm.create(params=params)
    except virt_vm.VMCreateError as e:
        o = e.output
    else:
        test.fail("Test failed since vm shouldn't be launched")
    error_context.context(
        "Check the expected error message: %s" % error_msg, test.log.info
    )
    if not re.search(error_msg, o):  # pylint: disable=E0601
        test.fail("Can not get expected error message: %s from %s" % (error_msg, o))
