from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    1) Boot a guest with "-cpu host,+invtsc" or "-cpu $cpu_model,+invtsc".
    2) Check current clocksource and available clocksource and nonstop_tsc flag
    in guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Check current cloclsource", test.log.info)
    cur_clksrc_cmd = params["cur_clksrc_cmd"]
    current_clksrc = session.cmd_output_safe(cur_clksrc_cmd)
    avl_clksrc_cmd = params["avl_clksrc_cmd"]
    avl_clksrc = session.cmd_output_safe(avl_clksrc_cmd)
    check_tsc_flag_cmd = params["check_tsc_flag_cmd"]
    tsc_flag = session.cmd_status(check_tsc_flag_cmd)
    expect_cur_clk = params["expect_cur_clk"]
    expect_avl_clk = params["expect_avl_clk"]
    expect_tsc_flag = params["expect_tsc_flag"]

    if expect_cur_clk not in current_clksrc:
        test.fail(
            "Current clocksource is %s, the expected is %s."
            % (current_clksrc, expect_cur_clk)
        )
    if tsc_flag:
        test.fail("Can not get expected flag: %s." % expect_tsc_flag)

    if expect_avl_clk not in avl_clksrc:
        test.fail(
            "Available clocksources are %s, the exected are %s."
            % (avl_clksrc, expect_avl_clk)
        )
