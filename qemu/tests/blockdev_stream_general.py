from provider import job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamGeneralTest(BlockdevStreamNowaitTest):
    """Do block-stream with general operations"""

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        job_utils.check_block_jobs_started(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_started_timeout", 30),
        )
        self.main_vm.monitor.cmd("job-pause", {"id": self._job})
        job_utils.wait_until_job_status_match(
            self.main_vm,
            "paused",
            self._job,
            self.params.get_numeric("job_paused_interval", 30),
        )
        self.main_vm.monitor.cmd(
            "block-job-set-speed",
            {"device": self._job, "speed": self.params.get_numeric("resume_speed")},
        )
        self.main_vm.monitor.cmd("job-resume", {"id": self._job})
        job_utils.wait_until_job_status_match(
            self.main_vm,
            "running",
            self._job,
            self.params.get_numeric("job_running_timeout", 300),
        )
        self.main_vm.monitor.cmd("job-cancel", {"id": self._job})
        event = job_utils.get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_CANCELLED",
            self.params.get_numeric("job_cancelled_timeout", 30),
            device=self._job,
        )
        if not event:
            self.test.fail("Failed to get BLOCK_JOB_CANCELLED event for %s" % self._job)
        job_utils.block_job_dismiss(self.main_vm, self._job)
        self._stream_options["speed"] = 0
        self.blockdev_stream()
        self.wait_stream_job_completed()
        self.check_backing_file()
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    Do block-stream with auto-finalize/auto-dismiss on/off
    test steps:
        1. boot VM with a data image
        2. do block-stream with auto-finalize/auto-dismiss on/off
        3. pause/resume/cancel/re-start stream job
        4. check there is nothing wrong
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamGeneralTest(test, params, env)
    stream_test.run_test()
