import random
import time

from virttest import error_context, utils_test

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestLinux, BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Balloon service test, i.e. guest-stats-polling-interval test.
    1) boot a guest with balloon device.
    2) enable and check driver verifier in guest(only for windows guest).
    3) install balloon service in guest(only for windows guest).
    4) evict / enlarge balloon.
    5) get polling value in qmp, then do memory check if necessary.
    6) uninstall or stop balloon service(optional)
    7) check memory status(optional)
    8) install or run balloon service(optional)
    9) check memory status(optional)
    10) uninstall balloon service and clear driver verifier(only for
       windows guest).
    """

    def balloon_memory(vm, mem_check, min_sz, max_sz):
        """
        Doing memory balloon in a loop and check memory statistics during balloon.

        :param vm: VM object.
        :param mem_check: need to do memory check if param mem_check is 'yes'
        :param min_sz: guest minimal memory size
        :param max_sz: guest maximal memory size
        """
        repeat_times = int(params.get("repeat_times", 5))
        test.log.info("repeat times: %d", repeat_times)

        while repeat_times:
            for tag in params.objects("test_tags"):
                error_context.context("Running %s test" % tag, test.log.info)
                params_tag = params.object_params(tag)
                balloon_type = params_tag["balloon_type"]
                if balloon_type == "evict":
                    expect_mem = int(
                        random.uniform(min_sz, balloon_test.get_ballooned_memory())
                    )
                else:
                    expect_mem = int(
                        random.uniform(balloon_test.get_ballooned_memory(), max_sz)
                    )

                quit_after_test = balloon_test.run_ballooning_test(expect_mem, tag)
                time.sleep(20)
                if mem_check == "yes":
                    check_list = params["mem_stat_check_list"].split()
                    for mem_check_name in check_list:
                        balloon_test.memory_stats_check(
                            mem_check_name, mem_stat_working
                        )
                if quit_after_test:
                    return

            repeat_times -= 1

    mem_check = params.get("mem_check", "yes")
    mem_stat_working = True

    error_context.context("Boot guest with balloon device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login()
    if params["os_type"] == "windows":
        driver_name = params.get("driver_name", "balloon")
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        balloon_test = BallooningTestWin(test, params, env)
        error_context.context("Config balloon service in guest", test.log.info)
        balloon_test.configure_balloon_service(session)
    else:
        balloon_test = BallooningTestLinux(test, params, env)

    try:
        min_sz, max_sz = balloon_test.get_memory_boundary()
        balloon_memory(vm, mem_check, min_sz, max_sz)
        blnsrv_operation = params.objects("blnsrv_operation")
        mem_stat_working = False
        for bln_oper in blnsrv_operation:
            error_context.context("%s balloon service" % bln_oper, test.log.info)
            balloon_test.operate_balloon_service(session, bln_oper)

            error_context.context(
                "Balloon vm memory after %s balloon service" % bln_oper, test.log.info
            )
            balloon_memory(vm, mem_check, min_sz, max_sz)
            mem_stat_working = True
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        session.close()
