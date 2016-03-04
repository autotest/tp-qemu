import time
import logging

from autotest.client.shared import error
from virttest import utils_misc
from virttest import utils_test


@error.context_aware
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

    error.context("Boot guest with balloon device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    default_memory = int(params.get("default_memory", 8192))
    unit = vm.monitor.protocol == "qmp" and 1048576 or 1
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    # for media player configuration
    if params.get("pre_cmd"):
        session.cmd(params.get("pre_cmd"))

    driver_name = params["driver_name"]
    if (params.get("need_enable_verifier"), "yes") == "yes":
        error.context("Enable %s driver verifier in guest" % driver_name,
                      logging.info)
        session = utils_test.qemu.setup_win_driver_verifier(session,
                                                            driver_name,
                                                            vm, timeout)

    error.context("Play video in guest", logging.info)
    play_video_cmd = params["play_video_cmd"]
    session.sendline(play_video_cmd)
    # need to wait for wmplayer loading remote video
    time.sleep(float(params.get("loading_timeout", 60)))
    check_playing_cmd = params["check_playing_cmd"]
    running = utils_misc.wait_for(lambda: session.cmd_status(
        check_playing_cmd) == 0, first=5.0, timeout=600)
    if not running:
        raise error.TestError("Video do not playing")

    env["balloon_test"] = 0
    error.context("balloon vm memory in loop", logging.info)
    repeat_times = int(params.get("repeat_times", 10))
    logging.info("repeat times: %d" % repeat_times)
    magnification = int(params.get("magnification", 512))
    logging.info("memory decrease magnification: %d" % magnification)
    start = magnification * unit
    end = default_memory * unit
    step = start
    while repeat_times:
        for memory in xrange(start, end, step):
            logging.debug("balloon vm mem to: %s B" % memory)
            vm.monitor.send_args_cmd("balloon value=%s" % memory)
            vm.monitor.query("balloon")
            logging.debug("balloon vm mem to: %s B" % memory)
            memory = end - memory
            vm.monitor.send_args_cmd("balloon value=%s" % memory)
            current_mem = vm.monitor.query("balloon")
            if current_mem != memory:
                env["balloon_test"] = 1
        repeat_times -= 1
    error.context("verify guest still alive", logging.info)
    session.cmd(params["stop_player_cmd"])
    vm.verify_alive()

    if (params.get("need_clear_verifier"), "yes") == "yes":
        error.context("Clear %s driver verifier in guest" % driver_name,
                      logging.info)
        session = utils_test.qemu.clear_win_driver_verifier(session, vm, timeout)
    if session:
        session.close()
