from provider.block_dirty_bitmap import block_dirty_bitmap_disable, get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkDisableBitmapTest(BlockdevLiveBackupBaseTest):
    """Disable bitmap test"""

    def _get_bitmaps(self):
        return list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
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
        self._disabled_bitmaps_info = self._get_bitmaps()

    def check_disabled_bitmaps(self):
        """bitmaps should be disabled, count should not change"""
        bitmaps_info = self._get_bitmaps()
        if not all(
            list(
                map(
                    lambda b1, b2: (
                        b1
                        and b2
                        and b1["count"] == b2["count"]  # same count
                        and b2["count"] > 0  # count > 0
                        and (b2["recording"] is False)
                    ),  # disabled
                    self._disabled_bitmaps_info,
                    bitmaps_info,
                )
            )
        ):
            self.test.fail("bitmaps count or status changed")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files("inc1")
        self.disable_bitmaps()
        self.generate_inc_files("inc2")
        self.check_disabled_bitmaps()


def run(test, params, env):
    """
    Disable bitmaps test

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add bitmap
        5. create a new file inc1
        6. disable bitmaps, record the count of bitmaps
        7. create a new file inc2
        8. check bitmaps disabled and count keeps the same

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkDisableBitmapTest(test, params, env)
    inc_test.run_test()
