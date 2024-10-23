from virttest import error_context, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Secured guest boot test:
    1) Log into a secure guest
    2) Check if there's error messagein

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    if params.get("start_vm") == "yes":
        session = vm.wait_for_serial_login()
        session.close()
        vm.destroy()
    else:
        error_msg = params.get("error_msg", "")
        try:
            vm.create(params=params)
            vm.verify_alive()
            output = vm.process.get_output()
            vm.destroy()
        except virt_vm.VMCreateError as detail:
            output = detail.output
        if error_msg not in output:
            test.fail(
                "Error message is not expected! " "Expected: {} Actual: {}".format(
                    error_msg, output
                )
            )
