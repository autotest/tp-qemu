import time

from virttest import error_context, utils_test
from virttest.qemu_monitor import QMPEventError

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Balloon negative test, balloon windows guest memory to very small value.
    1) boot a guest with balloon device.
    2) enable and check driver verifier in guest.
    3) evict guest memory to 10M.
    4) repeat step 3 for many times.
    5) check guest free memory.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    error_context.context("Boot guest with balloon device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    driver_name = params.get("driver_name", "balloon")
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_name
    )
    balloon_test = BallooningTestWin(test, params, env)
    expect_mem = int(params["expect_memory"])
    balloon_test.pre_mem = balloon_test.get_ballooned_memory()
    balloon_test.pre_gmem = balloon_test.get_memory_status()
    repeat_times = int(params.get("repeat_times", 10))

    while repeat_times:
        try:
            balloon_test.vm.balloon(expect_mem)
        except QMPEventError:
            pass
        balloon_test._balloon_post_action()
        time.sleep(30)
        repeat_times -= 1

    ballooned_memory = expect_mem - balloon_test.pre_mem
    balloon_test.memory_check("after balloon guest memory 10 times", ballooned_memory)
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
    session.close()
