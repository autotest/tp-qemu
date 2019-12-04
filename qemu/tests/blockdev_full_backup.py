from provider import blockdev_backup_base


def run(test, params, env):
    """
    backup VM disk test:

    1) start VM with data disk
    2) create target disk with qmp command
    3) full backup source disk to target disk
    4) shutdown VM
    5) compare source disk and target disk with qemu-img compare command
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    source = params.get("source_image")
    target = params.get("target_image")
    blockdev_test = blockdev_backup_base.BlockdevBackupSimpleTest(
        test, params, env, source, target)
    blockdev_test.run_test()
