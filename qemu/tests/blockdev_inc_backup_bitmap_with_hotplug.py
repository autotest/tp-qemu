from virttest.utils_misc import wait_for

from provider.block_dirty_bitmap import get_bitmap_by_name, get_bitmaps
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkAddBitmapToHotplugImg(BlockdevLiveBackupBaseTest):
    """Add bitmap to hot-plugged image"""

    def check_bitmap_count_gt_zero(self):
        """count of bitmaps should be 0"""
        bitmaps = list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )
        if not all(list(map(lambda b: b and b["count"] > 0, bitmaps))):
            self.test.fail("bitmap count should be greater than 0.")

    def hotplug_data_disk(self):
        tag = self._source_images[0]
        self._devices = self.main_vm.devices.images_define_by_params(
            tag, self.params.object_params(tag), "disk"
        )
        for dev in self._devices:
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def prepare_main_vm(self):
        super(BlockdevIncbkAddBitmapToHotplugImg, self).prepare_main_vm()
        self.hotplug_data_disk()

    def unplug_data_disk(self):
        """Unplug device and its format node"""
        for dev in self._devices[-1:-3:-1]:
            out = dev.unplug(self.main_vm.monitor)
            if not wait_for(
                lambda: dev.verify_unplug(out, self.main_vm.monitor),
                first=1,
                step=5,
                timeout=30,
            ):
                self.test.fail("Failed to unplug device")

    def check_bitmap_gone(self):
        out = self.main_vm.monitor.cmd("query-block")
        bitmaps = get_bitmaps(out)
        if not all([len(l) == 0 for l in bitmaps.values()]):
            self.test.fail("bitmap found unexpectedly after unplug")

    def prepare_test(self):
        if self.params.get("not_preprocess") == "yes":
            self.preprocess_data_disks()
        super(BlockdevIncbkAddBitmapToHotplugImg, self).prepare_test()

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.check_bitmap_count_gt_zero()
        self.unplug_data_disk()
        self.check_bitmap_gone()


def run(test, params, env):
    """
    Add disabled bitmaps test

    test steps:
        1. boot VM
        2. hot-plugged a 2G data disk
           format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add a bitmap to the hot-plugged data disk
        5. create another file
        6. check bitmap count should be greater than 0
        7. hot-unplug data disk(device and format node)
        8. check bitmap gone(not in output of query-block)

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkAddBitmapToHotplugImg(test, params, env)
    inc_test.run_test()
