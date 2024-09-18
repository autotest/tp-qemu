import aexpect

from provider.block_dirty_bitmap import get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.job_utils import get_event_by_condition


class BlockdevIncbkBitmapExistAfterVMCrashReboot(BlockdevLiveBackupBaseTest):
    """bitmap still exist after vm reboot caused by crash"""

    def check_bitmap_existed(self):
        """
        bitmap should exist after vm reboot.
        No need compare bitmap count with the original, for an
        active bitmap's count can be changed after reboot
        """
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
                    lambda b: b and (b["recording"] is True) and b["count"] >= 0,
                    bitmaps,
                )
            )
        ):
            self.test.fail("bitmap should still exist after vm crash.")

    def trigger_vm_crash(self):
        session = self.main_vm.wait_for_login(
            timeout=self.params.get_numeric("login_timeout", 300)
        )
        try:
            session.cmd(self.params["trigger_crash_cmd"], timeout=5)
        except aexpect.ShellTimeoutError:
            pass
        else:
            self.test.error("Error occurred when triggering vm crash")
        finally:
            session.close()

    def wait_till_vm_reboot(self):
        session = self.main_vm.wait_for_login(
            timeout=self.params.get_numeric("login_timeout", 360)
        )
        session.close()

    def check_vm_reset_event(self):
        tmo = self.params.get_numeric("vm_reset_timeout", 60)
        if get_event_by_condition(self.main_vm, "RESET", tmo) is None:
            self.test.fail("Failed to reset VM after triggering crash")

    def do_test(self):
        self.do_full_backup()
        self.trigger_vm_crash()
        self.check_vm_reset_event()
        self.wait_till_vm_reboot()
        self.check_bitmap_existed()


def run(test, params, env):
    """
    bitmap still exist after vm reboot caused by crash

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. trigger vm crash
        6. check bitmap still existed after vm reboot

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkBitmapExistAfterVMCrashReboot(test, params, env)
    inc_test.run_test()
