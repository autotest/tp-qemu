from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkAddBitmapToRawImgNeg(BlockdevLiveBackupBaseTest):
    """Negative test: Add bitmaps to a raw image"""

    def prepare_test(self):
        self.prepare_main_vm()

    def add_bitmap_to_raw_image(self):
        try:
            kargs = {
                "node": self._source_nodes[0],
                "name": self._bitmaps[0],
                "persistent": self._full_backup_options["persistent"],
            }
            self.main_vm.monitor.block_dirty_bitmap_add(**kargs)
        except QMPCmdError as e:
            error_msg = self.params["error_msg"].format(node=self._source_nodes[0])
            if error_msg not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("Adding bitmap succeeded unexpectedly")

    def do_test(self):
        self.add_bitmap_to_raw_image()


def run(test, params, env):
    """
    Add bitmaps to the raw image

    test steps:
        1. boot VM with a 2G data disk(format: raw)
        2. add persistent bitmap
        3. check the proper error message

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkAddBitmapToRawImgNeg(test, params, env)
    inc_test.run_test()
