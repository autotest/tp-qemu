import re

from virttest import error_context, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Nvdimm option align negative test:
    1) Boot vm with incorrect align options
    2) Check if can get the expected qemu output

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    params["start_vm"] = "yes"
    error_msg = params.get("error_msg", "")

    try:
        vm.create(params=params)
        output = vm.process.get_output()
    except virt_vm.VMCreateError as e:
        output = str(e)
    error_context.context(
        "Check the expected error message: %s" % error_msg, test.log.info
    )
    if not re.search(error_msg, output):
        test.fail("Can not get expected error message: %s" % error_msg)
