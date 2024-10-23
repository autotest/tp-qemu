import random

from virttest.utils_numeric import normalize_data_size

from provider.block_dirty_bitmap import get_bitmaps_in_device
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkMergeBitmapsDiffGranularityTest(BlockdevLiveBackupBaseTest):
    """Merge two bitmaps with different granularities"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkMergeBitmapsDiffGranularityTest, self).__init__(
            test, params, env
        )
        self._merged_bitmaps = params.objects("bitmap_merge_list")
        self._merged_target = params["bitmap_merge_target"]
        self._granularities = random.sample(
            params.objects("granularity_list"), len(self._merged_bitmaps)
        )

    def _get_bitmaps(self):
        return get_bitmaps_in_device(self.main_vm, self._source_nodes[0])

    def check_bitmaps_count(self):
        """count of both bitmaps should be greater than 0"""
        if not all(list(map(lambda b: b and b["count"] > 0, self._get_bitmaps()))):
            self.test.fail("bitmaps count should be greater than 0")

    def add_two_bitmaps(self):
        bitmaps = [
            {
                "node": self._source_nodes[0],
                "name": b,
                "granularity": int(normalize_data_size(g, "B")),
            }
            for b, g in zip(self._merged_bitmaps, self._granularities)
        ]
        job_list = [
            {"type": "block-dirty-bitmap-add", "data": data} for data in bitmaps
        ]
        self.main_vm.monitor.transaction(job_list)

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
        self.main_vm.monitor.transaction(job_list)

    def do_test(self):
        self.add_two_bitmaps()
        self.generate_inc_files()
        self.check_bitmaps_count()
        self.merge_two_bitmaps()


def run(test, params, env):
    """
    Test for merging bitmaps with different granularities

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. add two bitmaps
        5. create a new file
        6. check bitmap count > 0
        7. add a new disabled bitmap and merge the two bitmaps

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkMergeBitmapsDiffGranularityTest(test, params, env)
    inc_test.run_test()
