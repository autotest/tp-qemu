from virttest.utils_misc import wait_for

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorCancelReadyIOJobTest(BlockdevMirrorNowaitTest):
    """
    Cancel a ready job when doing io on source image
    """

    def dd_file_in_background(self):
        def _is_dd_running():
            return session.cmd_status("pidof dd") == 0

        session = self.main_vm.wait_for_login()
        try:
            session.sendline(self.params["write_file_cmd"])
            if not wait_for(lambda: _is_dd_running(), 30, 0, 1, "Waiting dd start..."):
                self.test.error("Failed to start dd in vm")
        finally:
            session.close()

    def cancel_job(self):
        self.main_vm.monitor.cmd(
            "block-job-cancel", {"device": self._jobs[0], "force": True}
        )
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_CANCELLED",
            self.params.get_numeric("job_cancelled_timeout", 60),
            device=self._jobs[0],
        )
        if event is None:
            self.test.fail("Job failed to cancel")

    def wait_till_job_ready(self):
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_READY",
            self.params.get_numeric("job_ready_timeout", 120),
            device=self._jobs[0],
        )
        if event is None:
            self.test.fail("Job failed to reach ready state")

    def do_test(self):
        self.blockdev_mirror()
        self.wait_till_job_ready()
        self.dd_file_in_background()
        self.cancel_job()


def run(test, params, env):
    """
    Cancel a ready job when doing io on source image

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. wait till job status changes to ready
        7. dd a file inside vm (background)
        8. cancel the ready job when doing dd in background

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorCancelReadyIOJobTest(test, params, env)
    mirror_test.run_test()
