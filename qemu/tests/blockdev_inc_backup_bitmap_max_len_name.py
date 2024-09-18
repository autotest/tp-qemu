import json
import re

from avocado.utils import process

from provider.block_dirty_bitmap import block_dirty_bitmap_add, get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkAddBitmapMaxLenName(BlockdevLiveBackupBaseTest):
    """Add a bitmap with the max len name(1023 chars)"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkAddBitmapMaxLenName, self).__init__(test, params, env)
        self._max_len_name = self._make_bitmap_name()

    def _make_bitmap_name(self):
        length = self.params.get_numeric("bitmap_name_max_len") - len(
            self.params["prefix_name"]
        )
        return (
            self.params["prefix_name"]
            + process.run(
                self.params["create_bitmap_name_cmd"].format(length=length),
                ignore_status=True,
                shell=True,
            )
            .stdout.decode()
            .strip()
        )

    def prepare_test(self):
        self.prepare_main_vm()

    def add_persistent_bitmap(self):
        kargs = {
            "bitmap_name": self._max_len_name,
            "target_device": self._source_nodes[0],
            "persistent": "on",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def check_image_bitmap_qemu_img(self):
        data_image_obj = self.source_disk_define_by_params(
            self.params, self._source_images[0]
        )
        try:
            out = json.loads(data_image_obj.info(True, "json"))
            bitmap = out["format-specific"]["data"]["bitmaps"][0]
        except Exception as e:
            self.test.fail("Failed to get bitmap: %s" % str(e))
        else:
            if bitmap["name"] != self._max_len_name:
                self.test.fail("Failed to get bitmap with qemu-img")

    def check_image_bitmap_with_qmp_cmd(self):
        bitmap = get_bitmap_by_name(
            self.main_vm, self._source_nodes[0], self._max_len_name
        )
        if bitmap is None:
            self.test.fail("Failed to get bitmap with query-block")

    def check_qemu_aborted(self):
        """We used to hit core once, so add this check for future detection"""
        with open(self.test.logfile, "r") as f:
            out = f.read().strip()
            if re.search(self.error_msg, out, re.M):
                self.test.fail("qemu aborted (core dumped)")

    def post_test(self):
        self.error_msg = "(core dumped)|%s Aborted" % self.main_vm.get_pid()
        super(BlockdevIncbkAddBitmapMaxLenName, self).post_test()
        self.check_qemu_aborted()

    def do_test(self):
        self.add_persistent_bitmap()
        self.main_vm.destroy()
        self.check_image_bitmap_qemu_img()
        self.main_vm.create()
        self.main_vm.verify_alive()
        self.check_image_bitmap_with_qmp_cmd()


def run(test, params, env):
    """
    Add a bitmap with the max len name(1023 chars)

    test steps:
        1. boot VM with a 2G data disk
        2. add persistent bitmap with max len bitmap name
        3. destroy VM
        4. check bitmap should exist with qemu-img
        5. restart VM
        6. check bitmap should exist with query-block
        7. destroy VM
        8. check core dump

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkAddBitmapMaxLenName(test, params, env)
    inc_test.run_test()
