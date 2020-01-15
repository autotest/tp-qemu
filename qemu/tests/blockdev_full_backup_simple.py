from provider.blockdev_full_backup_base import BlockdevFullBackupBaseTest


def run(test, params, env):
    """
    backup VM disk test:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk with qmp command
    4) full backup source disk to target disk
    5) shutdown VM
    6) boot VM with target disk
    7) check data file md5 not change in target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_test = BlockdevFullBackupBaseTest(test, params, env)
    blockdev_test.run_test()
