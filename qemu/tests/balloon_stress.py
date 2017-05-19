import logging
import random

from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from avocado.core import exceptions
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Qemu balloon device stress test:
    1) boot guest with balloon device
    2) enable driver verifier in guest
    3) reboot guest (optional)
    4) check device using right driver in guest.
    5) play online video in guest
    6) balloon memory in monitor in loop
    7) check vm alive

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Boot guest with balloon device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    driver_name = params["driver_name"]
    utils_test.qemu.setup_win_driver_verifier(driver_name, vm, timeout)

    error_context.context("Run video in background", logging.info)
    video_play = utils_misc.InterruptedThread(
        utils_test.run_virt_sub_test, (test, params, env),
        {"sub_type": params.get("sub_test")})
    video_play.start()

    check_playing_cmd = params["check_playing_cmd"]
    running = utils_misc.wait_for(
        lambda: utils_misc.get_guest_cmd_status_output(
            vm, check_playing_cmd)[0] == 0, first=60, timeout=600)
    if not running:
        raise exceptions.TestError("Video is not playing")

    error_context.context("balloon vm memory in loop", logging.info)
    repeat_times = int(params.get("repeat_times", 10))
    logging.info("repeat times: %d" % repeat_times)
    balloon_test = BallooningTestWin(test, params, env)
    min_sz, max_sz = balloon_test.get_memory_boundary()
    while repeat_times:
        balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
        repeat_times -= 1

    error_context.context("verify guest still alive", logging.info)
    vm.verify_alive()
    if session:
        session.close()
