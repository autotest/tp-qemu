import logging

from virttest import data_dir

from provider import backup_utils
from provider.blockdev_stream_base import BlockDevStreamTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevStreamBackingMaskOnTest(BlockDevStreamTest):
    """Do block-stream based on an existed snapshot in snapshot chain"""

    def __init__(self, test, params, env):
        super(BlockdevStreamBackingMaskOnTest, self).__init__(test, params, env)
        self._snapshot_images = self.params.objects("snapshot_images")
        self._trash = []

    def snapshot_test(self):
        """create one snapshot, create one new file"""
        self.generate_tempfile(
            self.disks_info[self.base_tag][1],
            filename="base",
            size=self.params["tempfile_size"],
        )

        # data->sn1->sn2->sn3->sn4
        chain = [self.base_tag] + self._snapshot_images
        for idx in range(1, len(chain)):
            backup_utils.blockdev_snapshot(
                self.main_vm, "drive_%s" % chain[idx - 1], "drive_%s" % chain[idx]
            )

            self.generate_tempfile(
                self.disks_info[self.base_tag][1],
                filename=chain[idx],
                size=self.params["tempfile_size"],
            )

    def _disk_define_by_params(self, tag):
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        return sp_admin.volume_define_by_params(tag, params)

    def prepare_snapshot_file(self):
        """hotplug all snapshot images"""
        for tag in self._snapshot_images:
            disk = self._disk_define_by_params(tag)
            disk.hotplug(self.main_vm)
            self._trash.append(disk)

    def _remove_images(self):
        for img in self._trash:
            sp_admin.remove_volume(img)

    def post_test(self):
        try:
            if self.main_vm.is_alive():
                self.main_vm.destroy()
            self._remove_images()
        except Exception as e:
            LOG_JOB.warning(str(e))

    def check_backing_format(self):
        base_format = self.base_image.get_format()
        output = self.snapshot_image.info(force_share=True).split("\n")
        for item in output:
            if "backing file format" in item:
                if base_format not in item:
                    self.test.fail(
                        "Expected format: %s, current format: %s"
                        % (item.split(":")[1], base_format)
                    )

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_backing_format()


def run(test, params, env):
    """
    Basic block stream test with stress
    test steps:
        1. boot VM with a data image
        2. add snapshot images
        3. create a file(base) on data image
        4. take snapshots(data->sn1->sn2->sn3i->sn4),
           take one snapshot, create one new file(snx, x=1,2,3,4)
        5. do block-stream (base-node:sn1, device: sn4)
        6. check backing format of the top node(data->sn4)
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamBackingMaskOnTest(test, params, env)
    stream_test.run_test()
