from virttest import error_context, utils_misc, utils_test

from generic.tests import guest_suspend


@error_context.context_aware
def run(test, params, env):
    """
    Run guest suspend under guest nic stress

    1) Boot up VM, and login guest
    2) Run bg_stress_test(pktgen, netperf or file copy) if needed
    3) Do guest suspend and resume test

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error_context.context("Init guest and try to login", test.log.info)
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    bg_stress_test = params.get("run_bgstress")
    try:
        if bg_stress_test:
            error_context.context(
                "Run test %s background" % bg_stress_test, test.log.info
            )
            stress_thread = ""
            wait_time = float(params.get("wait_bg_time", 60))
            bg_stress_run_flag = params.get("bg_stress_run_flag")
            env[bg_stress_run_flag] = False
            stress_thread = utils_misc.InterruptedThread(
                utils_test.run_virt_sub_test,
                (test, params, env),
                {"sub_type": bg_stress_test},
            )
            stress_thread.start()
            if not utils_misc.wait_for(
                lambda: env.get(bg_stress_run_flag),
                wait_time,
                0,
                5,
                "Wait %s test start" % bg_stress_test,
            ):
                test.error("Run stress test error")

        suspend_type = params.get("guest_suspend_type")
        error_context.context(
            "Run suspend '%s' test under stress" % suspend_type, test.log.info
        )
        bg_cmd = guest_suspend.run
        args = (test, params, env)
        bg = utils_test.BackgroundTest(bg_cmd, args)
        bg.start()
        if bg.is_alive():
            try:
                env[bg_stress_run_flag] = False
                bg.join()
            except Exception as e:
                err_msg = "Run guest suspend: '%s' error!\n" % suspend_type
                err_msg += "Error info: '%s'" % e
                test.fail(err_msg)

    finally:
        env[bg_stress_run_flag] = False
