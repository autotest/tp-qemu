import logging
import random

from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from qemu.tests.balloon_check import BallooningTestWin
from qemu.tests.balloon_check import BallooningTestLinux


@error_context.context_aware
def run(test, params, env):
    """
    Qemu balloon device stress test:
    1) boot guest with balloon device
    2) enable driver verifier in guest (Windows only)
    3) run stress in background repeatly
    4) balloon memory in monitor in loop

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def run_stress(test, params, env, vm):
        """
        Run stress in background
        """
        while True:
            if params['os_type'] == 'windows':
                utils_test.run_virt_sub_test(test, params, env,
                                             params.get("stress_test"))
            else:
                stress_bg = utils_test.VMStress(vm, "stress", params)
                stress_bg.load_stress_tool()

    error_context.context("Boot guest with balloon device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    if params['os_type'] == 'windows':
        driver_name = params["driver_name"]
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, driver_name,
                                                                timeout)
        balloon_test = BallooningTestWin(test, params, env)
    else:
        balloon_test = BallooningTestLinux(test, params, env)

    error_context.context("Run stress background", logging.info)
    bg = utils_misc.InterruptedThread(run_stress, (test, params, env, vm))
    bg.start()

    repeat_times = int(params.get("repeat_times", 1000))
    min_sz, max_sz = balloon_test.get_memory_boundary()

    error_context.context("balloon vm memory in loop", logging.info)
    try:
        for i in range(1, int(repeat_times+1)):
            logging.info("repeat times: %d" % i)
            balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
            if not bg.is_alive():
                test.error("Background stress process is not alive")
    finally:
        if session:
            session.close()
