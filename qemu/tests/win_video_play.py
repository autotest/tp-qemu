import logging
import time

from avocado.core import exceptions
from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Run video in Windows guest
    1) Boot guest with the device.
    2) Check if wmplayer is installed default
    3) Install kmplayer if wmplayer is not installed
    4) Run video

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_wmplayer_installed(session):
        """
        Check if wmplayer is installed

        :param session: VM session
        :return: return wmplayer.exe path
        """
        error_context.context("Check if wmplayer is installed", logging.info)
        install_path = params.get("wmplayer_path")
        check_cmd = 'dir "%s"|findstr /I wmplayer'
        check_cmd = params.get("wmplayer_check_cmd", check_cmd) % install_path
        if session.cmd_status(check_cmd) == 0:
            return install_path

    def check_kmplayer_installed(session):
        """
        Check if kmplayer is installed

        :param session: VM session
        :return: return kmplayer.exe path
        """
        error_context.context("Check if kmplayer is installed", logging.info)
        install_path = params.get("kmplayer_path")
        check_cmd = 'dir "%s"|findstr /I kmplayer'
        check_cmd = params.get("kmplayer_check_cmd", check_cmd) % install_path
        if session.cmd_status(check_cmd) != 0:
            kmplayer_install(session)
        return install_path

    def kmplayer_install(session):
        """
        Install kmplayer

        :param session: VM session
        """
        error_context.context("Install kmplayer ...", logging.info)
        guest_name = params["guest_name"]
        alias_map = params["guest_alias"]
        guest_list = dict([x.split(":") for x in alias_map.split(",")])
        guest_name = guest_list[guest_name]

        install_cmd = params["kmplayer_install_cmd"] % guest_name
        install_cmd = utils_misc.set_winutils_letter(session, install_cmd)
        s, o = session.cmd_status_output(install_cmd, timeout=240)
        if s != 0:
            raise exceptions.TestError("Failed to install kmplayer %s" % o)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    wmplayer = check_wmplayer_installed(session)
    if wmplayer:
        video_player = wmplayer
        if params.get("wmplayer_reg_cmd"):
            logging.info("Update regedit")
            session.cmd(params.get("wmplayer_reg_cmd"))
    else:
        kmplayer = check_kmplayer_installed(session)
        video_player = kmplayer

    video_url = params["video_url"]
    play_video_cmd = params["play_video_cmd"] % (video_player, video_url)
    error_context.context("Play video", logging.info)
    try:
        session.cmd(play_video_cmd, timeout=240)
        time.sleep(params.get("time_for_video", 240))
    except Exception, details:
        raise exceptions.TestFail(details)
    finally:
        error_context.context("Stop video", logging.info)
        session.cmd('del /f /s "%s"' % video_player, ignore_all_errors=True)
        session.close()
