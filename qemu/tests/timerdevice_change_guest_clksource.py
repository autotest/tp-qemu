import re

from virttest import error_context, utils_test, utils_time


@error_context.context_aware
def run(test, params, env):
    """
    Timer device check guest after update kernel line without kvmclock:

    1) Boot a guest with kvm-clock
    2) Check the current clocksource in guest
    3) Check the available clocksource in guest
    4) Update "clocksource=" parameter in guest kernel cli
    5) Boot guest system
    6) Check the current clocksource in guest

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def verify_guest_clock_source(session, expected):
        if expected not in session.cmd(cur_clk):
            test.fail("Guest didn't use '%s' clocksource" % expected)

    error_context.context("Boot a guest with kvm-clock", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Check the current clocksource in guest", test.log.info)
    cur_clk = params["cur_clk"]
    if "kvm-clock" not in session.cmd(cur_clk):
        error_context.context("Update guest kernel cli to kvm-clock", test.log.info)
        utils_time.update_clksrc(vm, clksrc="kvm-clock")
        session = vm.wait_for_login(timeout=timeout)
        verify_guest_clock_source(session, "kvm-clock")

    error_context.context("Check the available clocksource in guest", test.log.info)
    avl_clk = params["avl_clk"]
    try:
        available_clksrc_list = session.cmd(avl_clk).split()
    except Exception as detail:
        test.fail("Couldn't get guest available clock source." " Detail: '%s'" % detail)
    try:
        for avl_clksrc in available_clksrc_list:
            if avl_clksrc == "kvm-clock":
                continue
            error_context.context(
                "Update guest kernel cli to '%s'" % avl_clksrc, test.log.info
            )
            utils_time.update_clksrc(vm, clksrc=avl_clksrc)
            session = vm.wait_for_login(timeout=timeout)
            error_context.context(
                "Check the current clocksource in guest", test.log.info
            )
            verify_guest_clock_source(session, avl_clksrc)
    finally:
        error_context.context("Restore guest kernel cli", test.log.info)
        proc_cmdline = "cat /proc/cmdline"
        check_output = str(session.cmd(proc_cmdline, timeout=60))
        clk_removed = re.search("clocksource.*", check_output).group()
        utils_test.update_boot_option(vm, args_removed=clk_removed)
        session = vm.wait_for_login(timeout=timeout)
        verify_guest_clock_source(session, "kvm-clock")
