import json

from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevFullBackupWithBitmapTest(BlockdevLiveBackupBaseTest):
    def add_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def _get_full_backup_options(self):
        options = json.loads(self.params["full_backup_options"])
        self._convert_args(options)
        return options

    def do_full_backup(self):
        """
        Backup source image to target image
        """
        src = self._source_nodes[0]
        dst = self._full_bk_nodes[0]
        self._full_backup_options.update({"bitmap": self._bitmaps[0]})
        backup_cmd = backup_utils.blockdev_backup_qmp_cmd
        cmd, arguments = backup_cmd(src, dst, **self._full_backup_options)
        try:
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            qmp_error_msg = self.params.get("qmp_error_msg")
            if qmp_error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail("Do full backup with bitmap set")

    def do_test(self):
        self.add_bitmap()
        self.do_full_backup()


def run(test, params, env):
    """
    full backup to a non-exist target:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk and add it
    4) full backup from src to dst with bitmapset
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_with_bitmap = BlockdevFullBackupWithBitmapTest(test, params, env)
    blockdev_with_bitmap.run_test()
