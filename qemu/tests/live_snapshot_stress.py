import logging

from virttest import error_context, utils_misc, utils_test

from qemu.tests import live_snapshot_basic

LOG_JOB = logging.getLogger("avocado.test")


class LiveSnapshotStress(live_snapshot_basic.LiveSnapshot):
    def __init__(self, test, params, env, tag):
        super(LiveSnapshotStress, self).__init__(test, params, env, tag)

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
        if not utils_misc.wait_for(self.stress_app_running, timeout=360, step=5):
            self.test.fail("stress app isn't running")

    @error_context.context_aware
    def unload_stress(self):
        """
        stop stress app
        """

        def _unload_stress():
            session = self.get_session()
            cmd = self.params.get("stop_cmd")
            session.sendline(cmd)
            return not self.stress_app_running()

        error_context.context("stop stress app in guest", LOG_JOB.info)
        utils_misc.wait_for(
            _unload_stress,
            first=2.0,
            text="wait stress app quit",
            step=1.0,
            timeout=120,
        )

    def stress_app_running(self):
        """
        check stress app really run in background;
        """
        session = self.get_session()
        cmd = self.params.get("check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        return status == 0


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_stress test:
       1). load stress in guest.
       2). do live snapshot during stress.
       3). quit stress app, reboot guest(optional);
       4). verify guest can response correctly.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = LiveSnapshotStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        stress_test.create_snapshot()
        stress_test.action_after_finished()
    finally:
        stress_test.clean()
