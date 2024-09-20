from time import sleep

from provider.block_dirty_bitmap import get_bitmap_by_name
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.job_utils import BLOCK_JOB_COMPLETED_EVENT, get_event_by_condition


class BlockdevIncbkIncNospaceWithSyncMode(BlockdevLiveBackupBaseTest):
    """
    Do incremental backup to an image without enough space,
    set bitmap mode to: on-success or always, check bitmap count
    """

    def __init__(self, test, params, env):
        super(BlockdevIncbkIncNospaceWithSyncMode, self).__init__(test, params, env)
        self._inc_bitmap_mode = params["inc_bitmap_mode"]
        self._inc_bk_nodes = ["drive_%s" % t for t in self._target_images]

    def _get_bitmap_count(self):
        # let's wait some time to sync bitmap count, for on ppc the count
        # failed to be synced immediately after creating a new file
        sleep(10)

        bm = get_bitmap_by_name(self.main_vm, self._source_nodes[0], self._bitmaps[0])
        if bm:
            if bm.get("count", 0) <= 0:
                self.test.fail("Count of bitmap should be greater than 0")
            return bm["count"]
        else:
            self.test.fail("Failed to get bitmap")

    def do_incremental_backup(self):
        self.count_before_incbk = self._get_bitmap_count()
        self.inc_job_id = "job_%s" % self._inc_bk_nodes[0]
        args = {
            "device": self._source_nodes[0],
            "target": self._inc_bk_nodes[0],
            "sync": "bitmap",
            "job-id": self.inc_job_id,
            "bitmap": self._bitmaps[0],
            "bitmap-mode": self._inc_bitmap_mode,
        }
        self.main_vm.monitor.cmd("blockdev-backup", args)

    def check_no_space_error(self):
        tmo = self.params.get_numeric("job_completed_timeout", 360)
        cond = {"device": self.inc_job_id}
        event = get_event_by_condition(
            self.main_vm, BLOCK_JOB_COMPLETED_EVENT, tmo, **cond
        )
        if event:
            if event["data"].get("error") != self.params["error_msg"]:
                self.test.fail("Unexpected error: %s" % event["data"].get("error"))
        else:
            self.test.fail("Failed to get BLOCK_JOB_COMPLETED event")

    def check_bitmap_count(self):
        count_after_incbk = self._get_bitmap_count()
        if self._inc_bitmap_mode == "on-success":
            if self.count_before_incbk != count_after_incbk:
                self.test.fail("Count of bitmap changed after inc-backup")
        elif self._inc_bitmap_mode == "always":
            if self.count_before_incbk <= count_after_incbk:
                self.test.fail("Count of bitmap not changed after inc-backup")

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()
        self.check_no_space_error()
        self.check_bitmap_count()


def run(test, params, env):
    """
    Do incremental backup to an image without enough space

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands, note
           that space of incremental backup image is less then 110M
        4. do full backup and add non-persistent bitmap
        5. create another file (size 110M)
        6. do inc bakcup to an image without enough space,
           check no enough space error
           bitmap-mode=always, count should be less than before
           bitmap-mode=on-success, count should be the same as before

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkIncNospaceWithSyncMode(test, params, env)
    inc_test.run_test()
