from provider.blockdev_full_backup_parallel import BlockdevFullBackupParallelTest


class BlockdevFullBackupRebootTest(BlockdevFullBackupParallelTest):
    def vm_reset(self):
        self.main_vm.reboot(method="system_reset")


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk with qmp command
    4) reset vm and full backup source disk to target disk
    5) shutdown VM
    6) boot VM with target disk
    7) check data file md5 not change in target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_test = BlockdevFullBackupRebootTest(test, params, env)
    blockdev_test.run_test()
