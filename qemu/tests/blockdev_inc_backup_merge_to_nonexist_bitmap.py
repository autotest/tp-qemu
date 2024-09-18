from virttest.qemu_monitor import QMPCmdError

from provider.block_dirty_bitmap import block_dirty_bitmap_merge
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlkdevIncMergeToNonexistBitmap(BlockdevLiveBackupBaseTest):
    """Merge two bitmaps to a non-exist target"""

    def __init__(self, test, params, env):
        super(BlkdevIncMergeToNonexistBitmap, self).__init__(test, params, env)
        self._merged_bitmaps = params.objects("bitmap_merge_list")
        self._merged_target = params["bitmap_merge_target"]

    def add_two_bitmaps(self):
        bitmaps = [
            {"node": self._source_nodes[0], "name": bitmap}
            for bitmap in self._merged_bitmaps
        ]
        job_list = [
            {"type": "block-dirty-bitmap-add", "data": data} for data in bitmaps
        ]
        self.main_vm.monitor.transaction(job_list)

    def merge_two_bitmaps(self):
        try:
            block_dirty_bitmap_merge(
                self.main_vm,
                self._source_nodes[0],
                self._merged_bitmaps,
                self._merged_target,
            )
        except QMPCmdError as e:
            nonexist_target = self._merged_target
            qmp_error_msg = self.params.get("qmp_error_msg") % nonexist_target
            if qmp_error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail("Merge to a non-exist bitmap:%s" % self._merged_target)

    def do_test(self):
        self.add_two_bitmaps()
        self.generate_inc_files()
        self.merge_two_bitmaps()


def run(test, params, env):
    """
    Test for merging bitmaps to a non-exist bitmap target

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add two bitmaps to data disk
        4. create a new file
        5. merge two bitmaps to a non-exist bitmap:bitmap_tmp

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mergeto_nexist_bp = BlkdevIncMergeToNonexistBitmap(test, params, env)
    mergeto_nexist_bp.run_test()
