import random

from virttest.utils_numeric import normalize_data_size

from provider.block_dirty_bitmap import get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkBitmapGranularityTest(BlockdevLiveBackupBaseTest):
    """bitmap with granularity testing"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkBitmapGranularityTest, self).__init__(test, params, env)
        self._set_granularity()

    def _set_granularity(self):
        granularities = self.params.objects("granularity_list")
        granularity = (
            random.choice(granularities)
            if granularities
            else self.params["granularity"]
        )
        self._full_backup_options["granularity"] = int(
            normalize_data_size(granularity, "B")
        )

    def _get_bitmaps(self):
        return list(
            map(
                lambda n, b: get_bitmap_by_name(self.main_vm, n, b),
                self._source_nodes,
                self._bitmaps,
            )
        )

    def check_bitmaps_granularity(self):
        bitmaps = self._get_bitmaps()
        granularity = self._full_backup_options["granularity"]
        if not all(list(map(lambda b: b.get("granularity") == granularity, bitmaps))):
            self.test.fail("Failed to set granularity")

    def do_test(self):
        self.do_full_backup()
        self.check_bitmaps_granularity()


def run(test, params, env):
    """
    bitmap with granularity test

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add bitmap with granularity set
        5. check granularity is exactly the one set in step 4

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkBitmapGranularityTest(test, params, env)
    inc_test.run_test()
