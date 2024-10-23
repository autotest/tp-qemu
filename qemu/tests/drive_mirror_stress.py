import logging
import time

from virttest import error_context, utils_misc, utils_test

from qemu.tests import drive_mirror

LOG_JOB = logging.getLogger("avocado.test")


class DriveMirrorStress(drive_mirror.DriveMirror):
    @error_context.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memory stress in guest;
        """
        error_context.context("launch stress app in guest", LOG_JOB.info)
        args = (self.test, self.params, self.env, self.params["stress_test"])
        bg_test = utils_test.BackgroundTest(utils_test.run_virt_sub_test, args)
        bg_test.start()
        if not utils_misc.wait_for(bg_test.is_alive, first=10, step=3, timeout=100):
            self.test.fail("background test start failed")
        if not utils_misc.wait_for(self.app_running, timeout=360, step=5):
            self.test.fail("stress app isn't running")
        # sleep 10s to ensure heavyload.exe make guest under heayload really;
        time.sleep(10)
        return None

    @error_context.context_aware
    def unload_stress(self):
        """
        stop stress app
        """

        def _unload_stress():
            session = self.get_session()
            cmd = self.params.get("stop_cmd")
            session.sendline(cmd)
            session.close()
            return self.app_running()

        error_context.context("stop stress app in guest", LOG_JOB.info)
        stopped = utils_misc.wait_for(
            _unload_stress,
            first=2.0,
            text="wait stress app quit",
            step=1.0,
            timeout=120,
        )
        if not stopped:
            LOG_JOB.warning("stress app is still running")

    def app_running(self):
        """
        check stress app really run in background;
        """
        session = self.get_session()
        cmd = self.params.get("check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        session.close()
        return status == 0

    @error_context.context_aware
    def verify_steady(self):
        """
        verify offset not decreased, after block mirror job in steady status;
        """
        error_context.context("verify offset not decreased", LOG_JOB.info)
        params = self.parser_test_args()
        timeout = int(params.get("hold_on_timeout", 600))
        offset = self.get_status()["offset"]
        start = time.time()
        while time.time() < start + timeout:
            _offset = self.get_status()["offset"]
            if _offset < offset:
                msg = "offset decreased, offset last: %s" % offset
                msg += "offset now: %s" % _offset
                self.test.fail(msg)
            offset = _offset


@error_context.context_aware
def run(test, params, env):
    """
    drive_mirror_stress test:
    1). load stress in guest
    2). mirror block device
    3). stop vm when mirroring job really run(optional)
    4). wait for block job in steady status
    5). check offset not decreased(optional)
    6). reopen new target image(optional)
    7). quit stress app, reboot guest(optional);
    8). verify guest can response correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = DriveMirrorStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        stress_test.start()
        stress_test.action_before_steady()
        stress_test.action_when_steady()
        stress_test.action_after_reopen()
    finally:
        stress_test.clean()
