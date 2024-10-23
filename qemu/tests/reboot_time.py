from virttest import env_process, error_context, utils_misc
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    KVM reboot time test:
    1) Set init run level to 1
    2) Restart guest
    3) Wait for the console
    4) Send a 'reboot' command to the guest
    5) Boot up the guest and measure the boot time
    6) Restore guest run level

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
        error_context.context("Restart guest", test.log.info)
        session.cmd("sync")
        vm.destroy()

        error_context.context("Boot up guest", test.log.info)
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_serial_login(timeout=timeout)

        error_context.context("Send a 'reboot' command to the guest", test.log.info)
        utils_memory.drop_caches()
        session.cmd("reboot & exit", timeout=1, ignore_all_errors=True)
        before_reboot_stamp = utils_misc.monotonic_time()

        error_context.context(
            "Boot up the guest and measure the boot time", test.log.info
        )
        session = vm.wait_for_serial_login(timeout=timeout)
        reboot_time = utils_misc.monotonic_time() - before_reboot_stamp
        test.write_test_keyval({"result": "%ss" % reboot_time})
        expect_time = int(params.get("expect_reboot_time", "30"))
        test.log.info("Reboot time: %ss", reboot_time)

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

    if reboot_time > expect_time:
        test.fail("Guest reboot is taking too long: %ss" % reboot_time)

    session.close()
