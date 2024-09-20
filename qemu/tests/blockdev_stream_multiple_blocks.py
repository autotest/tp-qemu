import logging

from provider import backup_utils
from provider.blockdev_base import BlockdevBaseTest
from provider.blockdev_stream_parallel import BlockdevStreamParallelTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevStreamMultipleBlocksTest(BlockdevStreamParallelTest, BlockdevBaseTest):
    """Do block-stream for multiple disks in parallel"""

    def __init__(self, test, params, env):
        super(BlockdevStreamMultipleBlocksTest, self).__init__(test, params, env)
        self._source_images = self.params.objects("source_images")
        self._snapshot_images = self.params.objects("snapshot_images")
        self.disks_info = {}  # tag, [dev, mount_point]
        self.files_info = {}  # tag, [file, file...]
        self.trash = []

    def generate_inc_files(self):
        """create another file on data disks"""
        for tag in self._source_images:
            self.generate_data_file(tag)

    def do_block_stream_on_another_image(self):
        """block-stream on another image"""
        arguments = {}
        device = "drive_%s" % self.params.objects("snapshot_images")[-1]
        backup_utils.blockdev_stream(self.main_vm, device, **arguments)

    def pre_test(self):
        self.prepare_data_disks()
        self.add_target_data_disks()

    def clone_vm_with_snapshots(self):
        """clone vm with snapshots instead of the original data images"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()

        self.clone_vm.params["images"] = " ".join(
            [self.clone_vm.params.objects("images")[0]] + self._snapshot_images
        )
        self.clone_vm.create()

    def create_snapshots(self):
        for idx, source in enumerate(self._source_images):
            backup_utils.blockdev_snapshot(
                self.main_vm,
                "drive_%s" % source,
                "drive_%s" % self._snapshot_images[idx],
            )

    def post_test(self):
        try:
            self.clone_vm.destroy()
            self.clean_images()
        except Exception as error:
            LOG_JOB.error(str(error))

    def do_test(self):
        self.create_snapshots()
        self.generate_inc_files()
        self.blockdev_stream()
        self.clone_vm_with_snapshots()
        self.verify_data_files()


def run(test, params, env):
    """
    Do block-stream for multiple blocks simultaneously

    test steps:
        1. boot VM with two 2G data disks
        2. format data disks and mount it
        3. create a file on both disks
        4. add snapshot images for both data disks
        5. create another file on both disks
        6. do block-stream for both disks in parallel
        7. restart VM with snapshot disks, check all files and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamMultipleBlocksTest(test, params, env)
    stream_test.run_test()
