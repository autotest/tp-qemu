import random
import time

from virttest import error_context, utils_test

from provider.blockdev_full_backup_parallel import BlockdevFullBackupParallelTest


class BlockdevFullBackupStressTest(BlockdevFullBackupParallelTest):
    def blockdev_backup(self):
        """sleep some secondes to wait VM load stress then do blockdev backup test."""
        time.sleep(random.randint(1, 4))
        super(BlockdevFullBackupStressTest, self).blockdev_backup()

    @error_context.context_aware
    def load_stress(self):
        error_context.context("load stress app in guest", self.test.log.info)
        stress_test = utils_test.VMStress(self.main_vm, "stress", self.params)
        stress_test.load_stress_tool()


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk with qmp command
    4) load stress in guest
    5) full backup source disk to target disk
    6) shutdown VM
    7) boot VM with target disk
    8) check data file md5 not change in target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_test = BlockdevFullBackupStressTest(test, params, env)
    blockdev_test.run_test()
