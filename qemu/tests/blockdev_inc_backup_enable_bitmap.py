from provider.block_dirty_bitmap import block_dirty_bitmap_enable, get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkEnableBitmapTest(BlockdevLiveBackupBaseTest):
    """Enable disabled bitmaps"""

    def _get_bitmaps(self):
        return list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def enable_bitmaps(self):
        list(
            map(
                lambda n, b: block_dirty_bitmap_enable(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def check_disabled_bitmaps_count(self):
        """count should always be 0"""
        if not all(list(map(lambda b: b and b["count"] == 0, self._get_bitmaps()))):
            self.test.fail("disabled bitmap count should always be 0")

    def check_enabled_bitmaps_count(self):
        """count should be greater than 0"""
        if not all(list(map(lambda b: b and b["count"] > 0, self._get_bitmaps()))):
            self.test.fail("active bitmap count should be greater than 0")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files("inc1")
        self.check_disabled_bitmaps_count()
        self.enable_bitmaps()
        self.generate_inc_files("inc2")
        self.check_enabled_bitmaps_count()


def run(test, params, env):
    """
    Enable bitmaps

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add disabled bitmap
        5. create a new file inc1
        6. check the count of bitmap should be 0
        7. enable the bitmap
        8. create a new file inc2
        9. check count of the bitmap should be greater than 0

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkEnableBitmapTest(test, params, env)
    inc_test.run_test()
