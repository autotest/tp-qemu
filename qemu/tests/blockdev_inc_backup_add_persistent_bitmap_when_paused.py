import json

from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkAddPersistentBitmapVMPaused(BlockdevLiveBackupBaseTest):
    """Add disabled bitmaps test"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkAddPersistentBitmapVMPaused, self).__init__(
            test, params, env
        )
        self._data_image_obj = self.source_disk_define_by_params(
            self.params, self._source_images[0]
        )

    def prepare_test(self):
        self.prepare_main_vm()

    def add_persistent_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
            "persistent": "on",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def _get_image_bitmap_info(self):
        try:
            out = json.loads(self._data_image_obj.info(True, "json"))
            return out["format-specific"]["data"]["bitmaps"][0]
        except Exception as e:
            self.test.fail("Failed to get bitmap info: %s" % str(e))

    def check_image_bitmap_existed(self):
        bitmap = self._get_image_bitmap_info()
        if bitmap["name"] != self._bitmaps[0]:
            self.test.fail("Persistent bitmap should exist in image")

    def check_image_bitmap_in_use(self):
        bitmap = self._get_image_bitmap_info()
        if "in-use" not in bitmap["flags"]:
            self.test.fail("Failed to check bitmap in-use flag")

    def do_test(self):
        self.main_vm.pause()
        self.add_persistent_bitmap()
        self.main_vm.resume()
        self.main_vm.destroy()
        self.check_image_bitmap_existed()
        self.main_vm.create()
        self.main_vm.verify_alive()
        self.main_vm.pause()
        self.check_image_bitmap_in_use()


def run(test, params, env):
    """
    Add persistent bitmap when vm is paused

    test steps:
        1. boot VM with a 2G data disk
        2. pause VM
        3. add persistent bitmap
        4. resume VM
        5. poweroff VM
        6. check bitmap should exist in image
        7. restart VM
        8. pause VM
        9. check bitmap should be in use in image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkAddPersistentBitmapVMPaused(test, params, env)
    inc_test.run_test()
