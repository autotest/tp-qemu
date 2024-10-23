from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlkFullBackupInvalidMaxWorkers(BlockdevLiveBackupBaseTest):
    def do_full_backup(self):
        max_workers = int(self.params["invalid_max_workers"])
        extra_options = {"max-workers": max_workers}
        cmd, arguments = backup_utils.blockdev_backup_qmp_cmd(
            self._source_nodes[0], self._full_bk_nodes[0], **extra_options
        )
        try:
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            error_msg = self.params["error_msg"]
            if error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail("Can do full backup with invalid max-workers")

    def do_test(self):
        self.do_full_backup()


def run(test, params, env):
    """
    backup test with invalid max-workers:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk with qmp command
    4) full backup source disk to target disk with invalid max-workers value

    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    backup_test = BlkFullBackupInvalidMaxWorkers(test, params, env)
    backup_test.run_test()
