from virttest import env_process, error_context, utils_misc
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    KVM boot time test:
    1) Set init run level to 1
    2) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    3) Boot up the guest and measure the boot time
    4) set init run level back to the old one

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Set guest run level to 1", test.log.info)
    single_user_cmd = params["single_user_cmd"]
    session.cmd(single_user_cmd)

    try:
        error_context.context("Shut down guest", test.log.info)
        session.cmd("sync")
        vm.destroy()

        error_context.context("Boot up guest and measure the boot time", test.log.info)
        utils_memory.drop_caches()
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_serial_login(timeout=timeout)
        boot_time = utils_misc.monotonic_time() - vm.start_monotonic_time
        test.write_test_keyval({"result": "%ss" % boot_time})
        expect_time = int(params.get("expect_bootup_time", "17"))
        test.log.info("Boot up time: %ss", boot_time)

    finally:
        try:
            error_context.context("Restore guest run level", test.log.info)
            restore_level_cmd = params["restore_level_cmd"]
            session.cmd(restore_level_cmd)
            session.cmd("sync")
            vm.destroy(gracefully=False)
            env_process.preprocess_vm(test, params, env, vm.name)
            vm.verify_alive()
            vm.wait_for_login(timeout=timeout)
        except Exception:
            test.log.warning(
                "Can not restore guest run level, " "need restore the image"
            )
            params["restore_image_after_testing"] = "yes"

    if boot_time > expect_time:
        test.fail("Guest boot up is taking too long: %ss" % boot_time)

    session.close()
