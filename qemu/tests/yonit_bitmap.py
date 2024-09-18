import signal

from virttest import error_context, utils_misc

from generic.tests import guest_test


@error_context.context_aware
def run(test, params, env):
    """
    Run yonit bitmap benchmark in Windows guests, especially win7 32bit,
    for regression test of BZ #556455.

    Run the benchmark (infinite) loop background using
    run_guest_test_background, and detect the existence of the process
    in guest.

      1. If the process exits before test timeout, that means the benchmark
      exits unexpectedly, and BSOD may have happened, which can be verified
      from the screenshot saved by virt-test.
      2. If just timeout happen, this test passes, i.e. the guest stays
      good while running the benchmark in the given time.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    sec_per_day = 86400  # seconds per day
    test_timeout = int(params.get("test_timeout", sec_per_day))
    login_timeout = int(params.get("login_timeout", 360))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=login_timeout)

    # Since the benchmark runs into an infinite loop, the background process
    # will never return, unless we get a BSOD.
    #
    # We set the test_timeout of the background guest_test much bigger than
    # that of this test to make sure that the background benchmark is still
    # running while the the foreground detecting is on going.
    error_context.context("run benchmark test in background", test.log.info)
    params["test_timeout"] = test_timeout * 2 + sec_per_day
    test.log.info("set Yonit bitmap test timeout to" " %ss", params["test_timeout"])
    pid = guest_test.run_guest_test_background(test, params, env)
    if pid < 0:
        session.close()
        test.error("Could not create child process to execute " "guest_test background")

    def is_yonit_benchmark_launched():
        if session.cmd_status('tasklist | find /I "compress_benchmark_loop"') != 0:
            test.log.debug("yonit bitmap benchmark was not found")
            return False
        return True

    error_context.context(
        "Watching Yonit bitmap benchmark is" " running until timeout", test.log.info
    )
    try:
        # Start detecting whether the benchmark is started a few mins
        # after the background test launched, as the downloading
        # will take some time.
        launch_timeout = login_timeout
        if utils_misc.wait_for(is_yonit_benchmark_launched, launch_timeout, 180, 5):
            test.log.debug("Yonit bitmap benchmark was launched successfully")
        else:
            test.error("Failed to launch yonit bitmap benchmark")

        # If the benchmark exits before timeout, errors happened.
        if utils_misc.wait_for(
            lambda: not is_yonit_benchmark_launched(), test_timeout, 60, 10
        ):
            test.error("Yonit bitmap benchmark exits unexpectly")
        else:
            if session.is_responsive():
                test.log.info("Guest stays good until test timeout")
            else:
                test.fail("Guest is dead")
    finally:
        test.log.info("Kill the background benchmark tracking process")
        utils_misc.safe_kill(pid, signal.SIGKILL)
        guest_test.wait_guest_test_background(pid)
        session.close()
