from provider.block_dirty_bitmap import (
    block_dirty_bitmap_clear,
    block_dirty_bitmap_disable,
    get_bitmap_by_name,
)
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkClearBitmapTest(BlockdevLiveBackupBaseTest):
    """Clear enabled/disabled bitmaps"""

    def clear_bitmaps(self):
        """
        Clear a bitmap.
        Note that block_dirty_bitmap_clear will also check the count
        of the bitmap should be 0, so no more check is needed after
        clearing the bitmap.
        """
        list(
            map(
                lambda n, b: block_dirty_bitmap_clear(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def disable_bitmaps(self):
        list(
            map(
                lambda n, b: block_dirty_bitmap_disable(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def check_bitmaps_count_gt_zero(self):
        """active bitmap's count should be greater than 0 after file writing"""
        bitmaps_info = list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )
        if not all(list(map(lambda b: b and b["count"] > 0, bitmaps_info))):
            self.test.fail("bitmaps count should be greater than 0")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files("inc1")
        self.check_bitmaps_count_gt_zero()
        self.clear_bitmaps()
        self.generate_inc_files("inc2")
        self.check_bitmaps_count_gt_zero()
        self.disable_bitmaps()
        self.clear_bitmaps()


def run(test, params, env):
    """
    Test for clearing enabled/disable bitmaps

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add bitmap
        5. create a new file inc1, check count of bitmap is greater than 0
        6. clear bitmap, check the count of bitmap should be 0
        7. create a new file inc2, check count of bitmap is greater than 0
        8. disable bitmap
        9. clear bitmap, check the count of bitmap should be 0

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkClearBitmapTest(test, params, env)
    inc_test.run_test()
