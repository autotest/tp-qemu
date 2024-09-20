from provider.block_dirty_bitmap import get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkAddDisabledBitmapTest(BlockdevLiveBackupBaseTest):
    """Add disabled bitmaps test"""

    def check_disabled_bitmaps(self):
        """count of bitmaps should be 0"""
        bitmaps = list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )
        if not all(
            list(
                map(
                    lambda b: b and (b["recording"] is False) and b["count"] == 0,
                    bitmaps,
                )
            )
        ):
            self.test.fail("disabled bitmaps changed.")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.check_disabled_bitmaps()


def run(test, params, env):
    """
    Add disabled bitmaps test

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add disabled bitmap
        5. create another file
        6. check bitmap should be disabled and count should be 0

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkAddDisabledBitmapTest(test, params, env)
    inc_test.run_test()
