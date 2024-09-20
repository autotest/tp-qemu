from provider import backup_utils, job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamPowerdown(BlockdevStreamNowaitTest):
    """Powerdown during stream"""

    def start_vm_with_snapshot(self):
        self.main_vm.destroy()
        self.snapshot_image.base_tag = self.base_tag
        self.snapshot_image.base_format = self.base_image.get_format()
        base_image_filename = self.base_image.image_filename
        self.snapshot_image.base_image_filename = base_image_filename
        self.snapshot_image.rebase(self.snapshot_image.params)
        self.clone_vm.create()

    def stream_with_clone_vm(self):
        job_id = backup_utils.blockdev_stream_nowait(
            self.clone_vm, self._top_device, **self._stream_options
        )
        job_utils.wait_until_block_job_completed(self.clone_vm, job_id)

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        job_utils.check_block_jobs_started(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_started_timeout", 30),
        )
        self.main_vm.monitor.cmd("quit")
        self.start_vm_with_snapshot()
        self.stream_with_clone_vm()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    Powerdown during stream
    test steps:
        1. boot VM with a data image
        2. create snapshot chain: data1->data1sn
        3. start stream from data to data1sn
        4. powerdown during stream
        5. rebase from data1sn to data1
        6. restart vm with data1sn, do stream.
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamPowerdown(test, params, env)
    stream_test.run_test()
