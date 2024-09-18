from virttest.qemu_monitor import QMPCmdError

from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlkdevIncMergeWithNonexistBitmap(BlockdevLiveBackupBaseTest):
    """Merge bitmaps with a non-exist bitmap to the target bitmap"""

    def __init__(self, test, params, env):
        super(BlkdevIncMergeWithNonexistBitmap, self).__init__(test, params, env)
        self._merged_bitmaps = params.objects("bitmap_merge_list")
        self._merged_target = params["bitmap_merge_target"]

    def add_one_bitmap(self):
        args = {
            "target_device": self._source_nodes[0],
            "bitmap_name": self._merged_bitmaps[0],
        }
        block_dirty_bitmap_add(self.main_vm, args)

    def merge_two_bitmaps(self):
        target_bitmap = {
            "node": self._source_nodes[0],
            "name": self._merged_target,
            "disabled": True,
        }
        merged_bitmap = {
            "node": self._source_nodes[0],
            "bitmaps": self._merged_bitmaps,
            "target": self._merged_target,
        }
        job_list = [
            {"type": "block-dirty-bitmap-add", "data": target_bitmap},
            {"type": "block-dirty-bitmap-merge", "data": merged_bitmap},
        ]
        try:
            self.main_vm.monitor.transaction(job_list)
        except QMPCmdError as e:
            nonexist_bitmap = self._merged_bitmaps[1]
            qmp_error_msg = self.params.get("qmp_error_msg") % nonexist_bitmap
            if qmp_error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail(
                "Can merge with a non-exist bitmap:%s" % self._merged_bitmaps[1]
            )

    def do_test(self):
        self.add_one_bitmap()
        self.generate_inc_files()
        self.merge_two_bitmaps()


def run(test, params, env):
    """
    Test for merging bitmaps with a non-exist bitmap

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add a bitmap to data disk
        4. create a new file
        5. add a new disabled bitmap, do bitmaps merge with
           a non-exist bitmap:bitmap1

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    merge_nexist_bp = BlkdevIncMergeWithNonexistBitmap(test, params, env)
    merge_nexist_bp.run_test()
