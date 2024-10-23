import logging

from virttest import data_dir, error_context
from virttest.qemu_capabilities import Flags

from provider import backup_utils
from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlkSnapshotWithDatafile(BlockDevSnapshotTest):
    def __init__(self, test, params, env):
        super(BlkSnapshotWithDatafile, self).__init__(test, params, env)
        self.trash = []

    def prepare_snapshot_file(self):
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        image_with_datafile = backup_utils.create_image_with_data_file
        images = image_with_datafile(self.main_vm, params, self.snapshot_tag)
        self.trash.extend(images)

    def check_data_file_in_block_info(self):
        block_info = self.main_vm.monitor.query("block")
        for item in block_info:
            filename = item["inserted"]["image"]["filename"]
            if self.snapshot_tag in filename:
                if "data-file" in filename:
                    data_file_tag = self.params[
                        "image_data_file_%s" % self.snapshot_tag
                    ]
                    data_file_image = self.get_image_by_tag(data_file_tag)
                    data_file = eval(filename.lstrip("json:"))["data-file"]
                    if self.main_vm.check_capability(
                        Flags.BLOCKJOB_BACKING_MASK_PROTOCOL
                    ):
                        data_filename = data_file["filename"]
                    else:
                        data_filename = data_file["file"]["filename"]
                    if data_filename != data_file_image.image_filename:
                        self.test.fail(
                            "data-file info is not as expected: %s"
                            % data_file_image.image_filename
                        )
                    break
                else:
                    self.test.fail("Data-file option not included in block info")
        else:
            self.test.fail("Device: %s not found in block info" % self.snapshot_tag)

    def snapshot_test(self):
        self.create_snapshot()
        self.check_data_file_in_block_info()
        for info in self.disks_info.values():
            self.generate_tempfile(info[1])
        self.verify_snapshot()

    def post_test(self):
        try:
            self.clone_vm.destroy()
            for image in self.trash:
                sp_admin.remove_volume(image)
        except Exception as error:
            LOG_JOB.error(str(error))


@error_context.context_aware
def run(test, params, env):
    """
    Block device snapshot test
    1) Start VM with a data disk
    2) Create snapshot target with data file
    3) Do snapshot, check data file info then
       save a temp file and record md5sum
    4) Rebase snapshot file
    5) Boot VM with Snapshot image as data disk
    6) Check temp file md5sum

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    snapshot_test = BlkSnapshotWithDatafile(test, params, env)
    snapshot_test.run_test()
