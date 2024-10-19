from functools import partial

from virttest.qemu_monitor import QMPCmdError

from provider import job_utils
from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorSpeedTest(BlockdevMirrorNowaitTest):
    """
    blockdev-mirror speed test
    """

    def test_invalid_speeds(self):
        """
        Set an invalid speed, make sure we can get the proper error message
        """

        def _set_invalid_speed(jobid, speed, error_msg):
            try:
                self.main_vm.monitor.cmd(
                    "block-job-set-speed", {"device": jobid, "speed": speed}
                )
            except QMPCmdError as e:
                if error_msg not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("block-job-set-speed %s succeeded unexpectedly" % speed)

        def _invalid_speed_error_tuple(speed):
            if "-" in speed:  # a negative int
                return int(speed), self.params["error_msg_negative"]
            elif "." in speed:  # a float number
                return float(speed), self.params["error_msg"]
            else:  # a string
                return speed, self.params["error_msg"]

        for speed in self.params.objects("invalid_speeds"):
            s, m = _invalid_speed_error_tuple(speed)
            func = partial(_set_invalid_speed, speed=s, error_msg=m)
            list(map(func, self._jobs))

    def test_valid_speeds(self):
        """
        Set a valid speed, make sure mirror job can go on without any issue
        """

        def _set_valid_speed(jobid, speed):
            self.main_vm.monitor.cmd(
                "block-job-set-speed", {"device": jobid, "speed": speed}
            )

        def _check_valid_speed(jobid, speed):
            job = job_utils.get_block_job_by_id(self.main_vm, jobid)
            if job.get("speed") != speed:
                self.test.fail(
                    "Speed:%s is not set as expected:%s" % (job.get("speed"), speed)
                )
            ck_speed = self.params.get_numeric("check_speed")
            uspeed = self.params.get_numeric("ulimit_speed")
            if speed > ck_speed or speed == uspeed:
                self.check_block_jobs_running(
                    self._jobs, self.params.get_numeric("mirror_running_timeout", 60)
                )

        for speed in self.params.objects("valid_speeds"):
            func = partial(_set_valid_speed, speed=int(speed))
            list(map(func, self._jobs))
            func_ck = partial(_set_valid_speed, speed=int(speed))
            list(map(func_ck, self._jobs))

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("mirror_started_timeout", 10)
        )
        self.test_invalid_speeds()
        self.test_valid_speeds()
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()


def run(test, params, env):
    """
    blockdev-mirror speed test

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. set an invalid speed, check error msg
        7. set a valid speed, check mirror job is running
        8. wait till mirror job completed
        9. check mirror nodes attached

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSpeedTest(test, params, env)
    mirror_test.run_test()
