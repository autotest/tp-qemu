import socket

from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest
from provider.job_utils import check_block_jobs_paused, check_block_jobs_started
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevStreamRemoteServerDownTest(BlockdevStreamNowaitTest):
    """
    Suspend/resume remote storage service while doing block stream
    """

    def __init__(self, test, params, env):
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )
        self.nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
        super(BlockdevStreamRemoteServerDownTest, self).__init__(test, params, env)

    def pre_test(self):
        self.nbd_export.create_image()
        try:
            self.nbd_export.export_image()
            super(BlockdevStreamRemoteServerDownTest, self).pre_test()
        except Exception:
            self.nbd_export.stop_export()
            raise

    def post_test(self):
        super(BlockdevStreamRemoteServerDownTest, self).post_test()
        self.nbd_export.stop_export()
        self.params["images"] += " %s" % self.params["local_image_tag"]

    def generate_tempfile(self, root_dir, filename, size="10M", timeout=360):
        """Create a large file to enlarge stream time"""
        super(BlockdevStreamRemoteServerDownTest, self).generate_tempfile(
            root_dir, filename, self.params["tempfile_size"], timeout
        )

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        check_block_jobs_started(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_started_timeout", 60),
        )
        self.nbd_export.suspend_export()
        try:
            check_block_jobs_paused(
                self.main_vm,
                [self._job],
                self.params.get_numeric("job_paused_interval", 50),
            )
        finally:
            self.nbd_export.resume_export()
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._job, "speed": 0}
        )
        self.wait_stream_job_completed()
        self.main_vm.destroy()
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    Suspend/resume remote storage service while doing block stream

    test steps:
        0. create a local image and export it with qemu-nbd
        1. boot VM with the nbd image exported above
        2. format the data disk and mount it
        3. hotplug a snapshot image for data image
        4. create a file 'base'
        5. take snapshot on data image
        6. create a file 'sn1'
        7. do blockdev-stream
        8. suspend nbd server
        9. stream job should be paused
       10. resume nbd server
       11. wait till stream job completed
       12. restart VM with snapshot disk, check all files and checksums

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamRemoteServerDownTest(test, params, env)
    stream_test.run_test()
