from functools import partial

from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkBitmapInuseTest(BlockdevLiveBackupBaseTest):
    """bitmap in-use cannot be used"""

    def __init__(self, test, params, env):
        self._inc1_bk_nodes = []
        self._inc2_bk_nodes = []
        super(BlockdevIncbkBitmapInuseTest, self).__init__(test, params, env)
        self._forbidden_actions = [
            partial(self.handle_bitmap, op=op)
            for op in self.params.objects("bitmap_forbidden_actions")
        ]
        self._forbidden_actions.append(
            partial(self.do_inc_backup, self._inc2_bk_nodes[0])
        )

    def _init_arguments_by_params(self, tag):
        super(BlockdevIncbkBitmapInuseTest, self)._init_arguments_by_params(tag)
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self._inc1_bk_nodes.append("drive_%s" % image_chain[1])
        self._inc2_bk_nodes.append("drive_%s" % image_chain[2])

    def handle_bitmap(self, op):
        self.main_vm.monitor.cmd(
            op, {"node": self._source_nodes[0], "name": self._bitmaps[0]}
        )

    def do_inc_backup(self, target, speed=0):
        self.main_vm.monitor.cmd(
            "blockdev-backup",
            {
                "device": self._source_nodes[0],
                "sync": "incremental",
                "target": target,
                "speed": speed,
                "bitmap": self._bitmaps[0],
                "job-id": "job_%s" % target,
            },
        )

    def do_forbidden_actions(self):
        """All these actions should fail with proper error message"""
        error_msg = self.params["error_msg"] % self._bitmaps[0]
        for action in self._forbidden_actions:
            try:
                action()
            except QMPCmdError as e:
                if error_msg not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("Unexpectedly succeeded")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_inc_backup(self._inc1_bk_nodes[0], 1024)
        self.do_forbidden_actions()


def run(test, params, env):
    """
    bitmap in-use cannot be used

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add bitmap
        5. generate another file
        6. do incremental backup with a low speed
        7. during backup, do the following:
           do incremental backup
           clear bitmap
           remove bitmap
           enable bitmap
           disable bitmap
           all should fail with proper error message

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkBitmapInuseTest(test, params, env)
    inc_test.run_test()
