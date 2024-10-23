import re

from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_full_backup_base import BlockdevFullBackupBaseTest


class BlockdevFullBackupNonexistTargetTest(BlockdevFullBackupBaseTest):
    def prepare_test(self):
        self.prepare_main_vm()
        self.prepare_data_disks()

    def do_backup(self):
        """
        Backup source image to target image
        """
        assert len(self.target_disks) >= len(
            self.source_disks
        ), "No enough target disks define in cfg!"
        src_lst = ["drive_%s" % x for x in self.source_disks]
        dst_lst = ["drive_%s" % x for x in self.target_disks]
        backup_cmd = backup_utils.blockdev_backup_qmp_cmd
        cmd, arguments = backup_cmd(src_lst[0], dst_lst[0], **self.backup_options)
        try:
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            qmp_error_msg = self.params.get("qmp_error_msg")
            if not re.search(qmp_error_msg, str(e.data)):
                self.test.fail(str(e))
        else:
            self.test.fail("Do full backup on a non-exist target")


def run(test, params, env):
    """
    full backup to a non-exist target:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) full backup source disk to a non-exist target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_nonexist_target = BlockdevFullBackupNonexistTargetTest(test, params, env)
    blockdev_nonexist_target.run_test()
