import logging
import random

from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Qemu balloon device stress test:
    1) boot guest with balloon device
    2) enable driver verifier in guest
    3) reboot guest (optional)
    4) check device using right driver in guest.
    5) play video in background repeatly
    6) balloon memory in monitor in loop

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def run_video():
        """
        Run video in background
        """
        while True:
            utils_test.run_virt_sub_test(test, params, env,
                                         params.get("video_test"))

    error_context.context("Boot guest with balloon device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    driver_name = params["driver_name"]
    utils_test.qemu.setup_win_driver_verifier(driver_name, vm, timeout)

    error_context.context("Run video background", logging.info)
    bg = utils_misc.InterruptedThread(run_video)
    bg.start()

    repeat_times = int(params.get("repeat_times", 500))
    balloon_test = BallooningTestWin(test, params, env)
    min_sz, max_sz = balloon_test.get_memory_boundary()

    error_context.context("balloon vm memory in loop", logging.info)
    try:
        for i in xrange(1, int(repeat_times+1)):
            logging.info("repeat times: %d" % i)
            balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
            if not bg.is_alive():
                test.error("Background video process is not playing")
    finally:
        if session:
            session.close()
