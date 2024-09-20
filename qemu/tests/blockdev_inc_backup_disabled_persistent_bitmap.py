from provider.block_dirty_bitmap import block_dirty_bitmap_disable, get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkDisPersistentBitmapTest(BlockdevLiveBackupBaseTest):
    """Disabled persistent bitmaps reload testing"""

    def check_disabled_bitmaps_after_vm_reboot(self):
        """bitmaps still disabled, and counts should keep the same as before"""
        bitmaps_info = self._get_bitmaps()
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
                    self._disabled_bitmaps_info,
                    bitmaps_info,
                )
            )
        ):
            self.test.fail("bitmaps' count or status changed")

    def disable_bitmaps(self):
        list(
            map(
                lambda n, b: block_dirty_bitmap_disable(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )
        self._disabled_bitmaps_info = self._get_bitmaps()

    def _get_bitmaps(self):
        return list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def check_image_bitmaps_existed(self):
        """Persistent bitmaps should be saved"""

        def _check(tag):
            out = self.source_disk_define_by_params(self.params, tag).info()
            if out:
                if self.params["check_bitmaps"] not in out:
                    self.test.fail("Persistent bitmaps should be saved in image")
            else:
                self.test.error("Error when querying image info with qemu-img")

        list(map(_check, self._source_images))

    def powerdown_vm(self):
        self.main_vm.monitor.system_powerdown()
        if not self.main_vm.wait_for_shutdown(
            self.params.get_numeric("shutdown_timeout", 360)
        ):
            self.test.fail("Failed to poweroff vm")

    def restart_vm(self):
        self.main_vm.create()
        self.main_vm.verify_alive()

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.disable_bitmaps()
        self.powerdown_vm()
        self.check_image_bitmaps_existed()
        self.restart_vm()
        self.check_disabled_bitmaps_after_vm_reboot()


def run(test, params, env):
    """
    Disabled persistent bitmaps testing

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add persistent bitmap
        5. create another file
        6. disable bitmaps, record the count of bitmaps
        7. poweroff vm
        8. check bitmaps saved from output of qemu-img info
        9. restart vm
       10. check bitmaps still disabled, count of bitmaps keep the same

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkDisPersistentBitmapTest(test, params, env)
    inc_test.run_test()
