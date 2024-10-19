from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorCompleteRunningJobTest(BlockdevMirrorNowaitTest):
    """
    Complete a running blockdev-mirror job
    """

    def complete_running_mirror_job(self):
        try:
            self.main_vm.monitor.cmd("job-complete", {"id": self._jobs[0]})
        except QMPCmdError as e:
            error_msg = self.params["error_msg"].format(job_id=self._jobs[0])
            if error_msg not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("job-complete completed unexpectedly")

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("job_started_timeout", 10)
        )
        self.complete_running_mirror_job()
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._jobs[0], "speed": 0}
        )
        self.wait_mirror_jobs_completed()


def run(test, params, env):
    """
    Complete a running blockdev-mirror job

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. complete the job when it's running, it should fail
        7. wait mirror job completed

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorCompleteRunningJobTest(test, params, env)
    mirror_test.run_test()
