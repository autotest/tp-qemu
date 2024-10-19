import re

from virttest import utils_misc, utils_qemu
from virttest.qemu_monitor import QMPCmdError
from virttest.utils_version import VersionInterval

from provider import backup_utils
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevFullBackupInvalidSyncTest(BlockdevLiveBackupBaseTest):
    def do_full_backup(self):
        """
        Backup source image to target image
        """
        src = self._source_nodes[0]
        dst = self._full_bk_nodes[0]
        backup_cmd = backup_utils.blockdev_backup_qmp_cmd
        cmd, arguments = backup_cmd(src, dst, **self._full_backup_options)
        try:
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            sync_mode = self._full_backup_options.get("sync")
            qemu_binary = utils_misc.get_qemu_binary(self.params)
            qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
            required_qemu_version = self.params["required_qemu_version"]
            if qemu_version in VersionInterval(required_qemu_version):
                qmp_error_msg = self.params["qmp_error_after_6_2"] % sync_mode
            else:
                qmp_error_msg = self.params["qmp_error_before_6_2"] % sync_mode
            if not re.search(qmp_error_msg, str(e.data)):
                self.test.fail(str(e))
        else:
            self.test.fail("Do full backup with an invalid sync mode")

    def do_test(self):
        self.do_full_backup()


def run(test, params, env):
    """
    full backup to a non-exist target:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk and add it
    4) full backup from src to dst with an invalid sync mode
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    blockdev_invalid_sync = BlockdevFullBackupInvalidSyncTest(test, params, env)
    blockdev_invalid_sync.run_test()
