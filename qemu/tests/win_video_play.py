import time

from avocado.core import exceptions
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Run video in Windows guest
    1) Boot guest with the device.
    2) Run video by mplayer

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    video_player = utils_misc.set_winutils_letter(session, params["mplayer_path"])
    video_url = params["video_url"]
    play_video_cmd = params["play_video_cmd"] % (video_player, video_url)
    error_context.context("Play video", test.log.info)
    try:
        session.cmd(play_video_cmd, timeout=240)
    except Exception as details:
        raise exceptions.TestFail(details)

    play_video_duration = params.get("play_video_duration")
    if play_video_duration:
        time.sleep(int(play_video_duration))
        session.cmd("taskkill /IM %s /F" % video_player, ignore_all_errors=True)
        session.close()
