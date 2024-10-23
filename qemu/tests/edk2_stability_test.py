from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Qemu edk2 stability test:
    1) Try to log into a guest
    2) Check serial log information
    3) Cycle the above process

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    check_messgae = params.get("check_messgae")
    timeout = params.get_numeric("login_timeout", 120)
    vm = env.get_vm(params["main_vm"])

    for i in range(params.get_numeric("reboot_count", 1)):
        vm.create()
        error_context.context("Check serial log result", test.log.info)
        try:
            vm.serial_console.read_until_output_matches(
                [check_messgae], timeout=timeout
            )
        except Exception as msg:
            test.log.error(msg)
            test.fail("No highlighted entry was detected " "the boot was abnormal.")
        vm.destroy(gracefully=False)
