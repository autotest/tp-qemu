from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorCancelRunningJob(BlockdevMirrorNowaitTest):
    """
    Cancel a running mirror job
    """

    def cancel_job(self):
        self.main_vm.monitor.cmd("block-job-cancel", {"device": self._jobs[0]})
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_CANCELLED",
            self.params.get_numeric("job_cancelled_timeout", 60),
            device=self._jobs[0],
        )
        if event is None:
            self.test.fail("Job failed to cancel")

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("job_started_timeout", 10)
        )
        self.cancel_job()


def run(test, params, env):
    """
    Cancel a running mirror job

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. cancel the running mirror job

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    cancel_running_mirror = BlockdevMirrorCancelRunningJob(test, params, env)
    cancel_running_mirror.run_test()
