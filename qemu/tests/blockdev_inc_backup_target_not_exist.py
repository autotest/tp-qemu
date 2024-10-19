import re

from virttest.qemu_monitor import QMPCmdError

from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkNonExistedTarget(BlockdevLiveBackupBaseTest):
    """Do incremental backup with a non-existed target"""

    def add_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
            "persistent": "off",
            "disabled": "off",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def prepare_test(self):
        self.prepare_main_vm()
        self.add_bitmap()

    def do_incremental_backup(self):
        try:
            self.main_vm.monitor.cmd(
                "blockdev-backup",
                {
                    "device": self._source_nodes[0],
                    "target": self.params["non_existed_target"],
                    "bitmap": self._bitmaps[0],
                    "sync": "incremental",
                },
            )
        except QMPCmdError as e:
            error_msg = self.params.get("error_msg")
            if not re.search(error_msg, str(e)):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("blockdev-backup succeeded unexpectedly")

    def do_test(self):
        self.do_incremental_backup()


def run(test, params, env):
    """
    Do incremental backup with a non-existed target

    test steps:
        1. boot VM
        2. hot-plug the backup image
        3. Do incremental backup with a non-existed target, proper
           error message should output

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkNonExistedTarget(test, params, env)
    inc_test.run_test()
