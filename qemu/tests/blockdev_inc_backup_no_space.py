import logging
import os

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.job_utils import BLOCK_JOB_COMPLETED_EVENT, get_event_by_condition

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevIncbkNoSpaceTest(BlockdevLiveBackupBaseTest):
    """Do full backup to an image without enough space"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkNoSpaceTest, self).__init__(test, params, env)
        self._bitmaps = []

    def release_target_space(self):
        LOG_JOB.info("Release space to extend target image size")
        os.unlink(self.params["dummy_image_file"])

    def check_no_space_error(self):
        # check 'error' message in BLOCK_JOB_COMPLETED event
        tmo = self.params.get_numeric("job_complete_timeout", 900)
        event = get_event_by_condition(self.main_vm, BLOCK_JOB_COMPLETED_EVENT, tmo)
        if event:
            if event["data"].get("error") != self.params["error_msg"]:
                self.test.fail("Unexpected error: %s" % event["data"].get("error"))
        else:
            self.test.fail("Failed to get BLOCK_JOB_COMPLETED event")

    def do_test(self):
        self.do_full_backup()
        self.check_no_space_error()
        self.release_target_space()
        self._full_backup_options["wait_job_complete"] = True
        self.do_full_backup()
        self.prepare_clone_vm()
        self.verify_data_files()


def run(test, params, env):
    """
    Do full backup to an image without enough space

    test steps:
        1. boot VM with a 2G data disk(actual size<2G)
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup
        5. wait till job done, check proper error message
        6. release space to make target image size extended(2G)
        7. do full backup and wait job done
        8. restart VM with the target image as its data image,
           check file and its md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkNoSpaceTest(test, params, env)
    inc_test.run_test()
