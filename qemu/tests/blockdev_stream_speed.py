from virttest.qemu_monitor import QMPCmdError

from provider import blockdev_stream_nowait
from provider import job_utils


class BlockdevStreamSpeedTest(blockdev_stream_nowait.BlockdevStreamNowaitTest):
    """
    blockdev-stream speed test
    """

    def test_invalid_speeds(self):
        """
        Set an invalid speed, make sure we can get the proper error message
        """
        def _set_invalid_speed(jobid, speed, error_msg):
            try:
                self.main_vm.monitor.cmd(
                    "block-job-set-speed", {'device': jobid, 'speed': speed})
            except QMPCmdError as e:
                if error_msg not in str(e):
                    self.test.fail('Unexpected error: %s' % str(e))
            else:
                self.test.fail('block-job-set-speed %s succeeded unexpectedly'
                               % speed)

        def _invalid_speed_error_tuple(speed):
            if '-' in speed:    # a negative int
                return int(speed), self.params['error_msg_negative']
            elif '.' in speed:  # a float number
                return float(speed), self.params['error_msg']
            else:               # a string
                return speed, self.params['error_msg']

        for speed in self.params.objects('invalid_speeds'):
            s, m = _invalid_speed_error_tuple(speed)
            _set_invalid_speed(self._job, s, m)

    def test_valid_speeds(self):
        """
        Set a valid speed, make sure stream job can go on without any issue
        """
        def _set_valid_speed(jobid, speed):
            self.main_vm.monitor.cmd(
                "block-job-set-speed", {'device': jobid, 'speed': speed})

        for speed in self.params.objects('valid_speeds'):
            _set_valid_speed(self._job, int(speed))
            job_utils.check_block_jobs_running(
                self.main_vm, [self._job],
                self.params.get_numeric('job_running_timeout', 300)
            )

    def generate_tempfile(self, root_dir, filename, size='10M', timeout=360):
        """Create a large file to enlarge stream time"""
        super(BlockdevStreamSpeedTest, self).generate_tempfile(
            root_dir, filename, self.params['tempfile_size'], timeout)

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        job_utils.check_block_jobs_started(
            self.main_vm, [self._job],
            self.params.get_numeric('job_started_timeout', 60)
        )
        self.test_invalid_speeds()
        self.test_valid_speeds()
        self.wait_stream_job_completed()
        self.check_backing_file()
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    blockdev-stream speed test

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a snapshot image for data image
        5. take snapshot on data image
        6. do blockdev-stream
        7. set an invalid speed, check error msg
        8. set a valid speed, check stream job is running
        9. wait till stream job completed
       10. restart VM with snapshot disk, check all files and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamSpeedTest(test, params, env)
    stream_test.run_test()
