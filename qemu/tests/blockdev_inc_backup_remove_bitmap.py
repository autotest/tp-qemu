from provider.block_dirty_bitmap import block_dirty_bitmap_remove, get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkRemoveBitmapTest(BlockdevLiveBackupBaseTest):
    """Persistent bitmaps remove testing"""

    def _get_bitmaps(self):
        return list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def remove_bitmaps(self):
        list(
            map(
                lambda n, b: block_dirty_bitmap_remove(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def check_bitmaps_gone_from_qmp(self):
        """bitmaps should be gone from output of query-block"""
        if any(list(map(lambda b: b is not None, self._get_bitmaps()))):
            self.test.fail("bitmap was found unexpectedly.")

    def check_bitmaps_count_gt_zero(self):
        """count should be greater than 0"""
        if not all(list(map(lambda b: b and b["count"] > 0, self._get_bitmaps()))):
            self.test.fail("bitmaps' count should be greater than 0")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.check_bitmaps_count_gt_zero()
        self.remove_bitmaps()
        self.check_bitmaps_gone_from_qmp()


def run(test, params, env):
    """
    Test for removing bitmap

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add a bitmap
        5. create another file
        6. check the count of bitmap is greater than 0
        7. remove bitmap
        8. check bitmap gone from output of query-block

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkRemoveBitmapTest(test, params, env)
    inc_test.run_test()
