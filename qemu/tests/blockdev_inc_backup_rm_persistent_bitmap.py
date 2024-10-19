from provider.block_dirty_bitmap import (
    block_dirty_bitmap_disable,
    block_dirty_bitmap_remove,
    get_bitmap_by_name,
)
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkRmPersistentBitmapTest(BlockdevLiveBackupBaseTest):
    """Persistent bitmaps remove testing"""

    def disable_bitmaps(self):
        list(
            map(
                lambda n, b: block_dirty_bitmap_disable(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def get_bitmaps(self):
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

    def powerdown_and_start_vm(self):
        self.main_vm.monitor.system_powerdown()
        if not self.main_vm.wait_for_shutdown(
            self.params.get_numeric("shutdown_timeout", 360)
        ):
            self.test.fail("Failed to poweroff vm")
        self.main_vm.create()
        self.main_vm.verify_alive()

    def check_image_bitmaps_gone(self):
        """bitmaps should be removed"""

        def _check(tag):
            out = self.source_disk_define_by_params(self.params, tag).info()
            if out:
                if self.params["check_bitmaps"] in out:
                    self.test.fail("Persistent bitmaps should be gone in image")
            else:
                self.test.error("Error when querying image info with qemu-img")

        list(map(_check, self._source_images))

    def check_bitmaps_not_changed(self):
        """bitmap's count should keep the same, status should be 'disabled'"""
        bitmaps_info = self.get_bitmaps()
        if not all(
            list(
                map(
                    lambda b1, b2: (
                        b1
                        and b2
                        and b2["count"] > 0
                        and b1["count"] == b2["count"]
                        and (b2["recording"] is False)
                    ),
                    self._bitmaps_info,
                    bitmaps_info,
                )
            )
        ):
            self.test.fail("bitmaps' count or status changed")

    def record_bitmaps_info(self):
        self._bitmaps_info = self.get_bitmaps()

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.record_bitmaps_info()
        self.disable_bitmaps()
        self.check_bitmaps_not_changed()
        self.powerdown_and_start_vm()
        self.check_bitmaps_not_changed()
        self.remove_bitmaps()
        self.main_vm.destroy()
        self.check_image_bitmaps_gone()


def run(test, params, env):
    """
    Persistent bitmaps removal testing

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add persistent bitmap
        5. create another file, record the count of bitmaps
        6. disable bitmaps, the count of bitmaps should keep the same
        7. poweroff&restart vm, the count of bitmaps should keep the same
        8. remove all bitmaps
        9. shutdown VM
       10. check bitmaps gone from output of qemu-img info

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkRmPersistentBitmapTest(test, params, env)
    inc_test.run_test()
