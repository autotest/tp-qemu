from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkNonExistedBitmap(BlockdevLiveBackupBaseTest):
    """Do incremental backup with a non-existed bitmap"""

    def prepare_test(self):
        self.prepare_main_vm()
        self.add_target_data_disks()

    def do_incremental_backup(self):
        try:
            self.main_vm.monitor.cmd(
                "blockdev-backup",
                {
                    "device": self._source_nodes[0],
                    "target": self._full_bk_nodes[0],
                    "bitmap": self.params["non_existed_bitmap"],
                    "sync": "incremental",
                },
            )
        except QMPCmdError as e:
            if self.params["error_msg"] not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("blockdev-backup succeeded unexpectedly")

    def do_test(self):
        self.do_incremental_backup()


def run(test, params, env):
    """
    Do incremental backup with a non-existed bitmap

    test steps:
        1. boot VM
        2. hot-plug the backup image
        3. Do incremental backup with a non-existed bitmap, proper
           error message should output

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkNonExistedBitmap(test, params, env)
    inc_test.run_test()
