from virttest import utils_disk

from provider import backup_utils
from provider.blockdev_full_backup_base import BlockdevFullBackupBaseTest


class BlockdevFullBackupMultiDisks(BlockdevFullBackupBaseTest):
    def format_data_disk(self, tag):
        session = self.main_vm.wait_for_login()
        try:
            info = backup_utils.get_disk_info_by_param(tag, self.params, session)
            assert info, "Disk not found in guest!"
            disk_path = "/dev/%s1" % info["kname"]
            mount_point = utils_disk.configure_empty_linux_disk(
                session, info["kname"], info["size"]
            )[0]
            self.disks_info[tag] = [disk_path, mount_point]
        finally:
            session.close()


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
    blockdev_test = BlockdevFullBackupMultiDisks(test, params, env)
    blockdev_test.run_test()
