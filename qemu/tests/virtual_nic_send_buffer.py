from virttest import error_context, remote, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test Steps:

    1. boot up guest with sndbuf=1048576 or other value.
    2. Transfer file between host and guest.
    3. Run netperf between host and guest.
    4. During netperf testing, from an external host ping the host whitch
       booting the guest.

    Params:
        :param test: QEMU test object.
        :param params: Dictionary with the test parameters.
        :param env: Dictionary with test environment.
    """

    dst_ses = None
    try:
        error_context.context("Transfer file between host and guest", test.log.info)
        utils_test.run_file_transfer(test, params, env)

        dsthost = params.get("dsthost")
        login_timeout = int(params.get("login_timeout", 360))
        if dsthost:
            params_host = params.object_params("dsthost")
            dst_ses = remote.wait_for_login(
                params_host.get("shell_client"),
                dsthost,
                params_host.get("shell_port"),
                params_host.get("username"),
                params_host.get("password"),
                params_host.get("shell_prompt"),
                timeout=login_timeout,
            )
        else:
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()
            dst_ses = vm.wait_for_login(timeout=login_timeout)
            dsthost = vm.get_address()

        bg_stress_test = params.get("background_stress_test", "netperf_stress")
        error_context.context(
            ("Run subtest %s between host and guest." % bg_stress_test), test.log.info
        )

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
            1,
            "Wait %s test start" % bg_stress_test,
        ):
            err = "Fail to start netperf test between guest and host"
            test.error(err)

        ping_timeout = int(params.get("ping_timeout", 60))
        host_ip = utils_net.get_host_ip_address(params)
        txt = "Ping %s from %s during netperf testing" % (host_ip, dsthost)
        error_context.context(txt, test.log.info)
        status, output = utils_test.ping(host_ip, session=dst_ses, timeout=ping_timeout)
        if status != 0:
            test.fail("Ping returns non-zero value %s" % output)

        package_lost = utils_test.get_loss_ratio(output)
        package_lost_ratio = float(params.get("package_lost_ratio", 5))
        txt = "%s%% packeage lost when ping %s from %s." % (
            package_lost,
            host_ip,
            dsthost,
        )
        if package_lost > package_lost_ratio:
            test.fail(txt)
        test.log.info(txt)

    finally:
        try:
            stress_thread.join(60)
        except Exception:
            pass
        if dst_ses:
            dst_ses.close()
