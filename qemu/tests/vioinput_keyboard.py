from virttest import error_context, utils_test

from provider.vioinput_basic import key_tap_test


@error_context.context_aware
def run(test, params, env):
    """
    Input keyboard test.

    1) Log into the guest.
    2) Check if the driver is installed and verified (only for win).
    3) Send key and Check if the correct key event can be received.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    driver = params["driver_name"]

    if params["os_type"] == "windows":
        session = vm.wait_for_login()

        error_context.context("Check vioinput driver is running", test.log.info)
        utils_test.qemu.windrv_verify_running(session, test, driver.split()[0])

        error_context.context(
            "Enable all vioinput related driver verified", test.log.info
        )
        session = utils_test.qemu.setup_win_driver_verifier(session, driver, vm)
        session.close()

    error_context.context("Run keyboard testing", test.log.info)
    key_tap_test(test, params, vm)
