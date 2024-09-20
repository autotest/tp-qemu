import os
import re

from virttest.qemu_monitor import QMPCmdError, get_monitor_function

from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkModRdonlyBitmapTest(BlockdevLiveBackupBaseTest):
    """Clear/Remove readonly bitmaps"""

    def prepare_test(self):
        self.prepare_main_vm()
        self._error_msg = "(core dumped)|{pid} Aborted".format(
            pid=self.main_vm.get_pid()
        )
        self.prepare_data_disks()

    def modify_readonly_bitmaps(self):
        for act in ["block-dirty-bitmap-clear", "block-dirty-bitmap-remove"]:
            f = get_monitor_function(self.main_vm, act)
            try:
                f(self._source_nodes[0], self._bitmaps[0])
            except QMPCmdError as e:
                error_msg = self.params["error_msg"].format(bitmap=self._bitmaps[0])
                if error_msg not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("%s succeeded unexpectedly" % act)

    def add_persistent_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
            "persistent": "on",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def restart_vm_with_readonly_data_image(self):
        self.main_vm.monitor.system_powerdown()
        if not self.main_vm.wait_until_dead(10, 1, 1):
            self.test.fail("Failed to shutdowm vm and save bitmap")
        self.params["image_readonly_%s" % self._source_images[0]] = "on"
        self.prepare_main_vm()
        self._error_msg += "|{pid} Aborted".format(pid=self.main_vm.get_pid())

    def check_qemu_aborted(self):
        """We used to hit core once, so add this check for future detection"""
        log_file = os.path.join(
            self.test.resultsdir, self.params.get("debug_log_file", "debug.log")
        )
        with open(log_file, "r") as f:
            out = f.read().strip()
            if re.search(self._error_msg, out, re.M):
                self.test.fail("qemu aborted (core dumped)")

    def do_test(self):
        self.add_persistent_bitmap()
        self.generate_inc_files("inc1")
        self.restart_vm_with_readonly_data_image()
        self.modify_readonly_bitmaps()
        self.check_qemu_aborted()


def run(test, params, env):
    """
    Clear/Remove the bitmap on a readonly image

    test steps:
        1. boot VM with a 2G data image
        2. add a persistent bitmap
        3. create a new file inc1
        4. poweroff vm and restart it with the readonly data image
        6. clear/remove the bitmap
        7. check the proper error message

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkModRdonlyBitmapTest(test, params, env)
    inc_test.run_test()
