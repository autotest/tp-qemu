import logging
import time

from virttest import error_context, utils_misc, utils_test

from qemu.tests import blk_stream

LOG_JOB = logging.getLogger("avocado.test")


class BlockStreamStress(blk_stream.BlockStream):
    @error_context.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memoery stress in guest;
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


def run(test, params, env):
    """
    block_stream_stress test:
    1). load stress in guest
    2). stream block device and wait to finished
    7). quit stress app
    8). reboot and verify guest can response correctly

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = BlockStreamStress(test, params, env, tag)
    try:
        stress_test.create_snapshots()
        stress_test.action_before_start()
        stress_test.start()
        stress_test.action_when_streaming()
        stress_test.action_after_finished()
    finally:
        stress_test.clean()
