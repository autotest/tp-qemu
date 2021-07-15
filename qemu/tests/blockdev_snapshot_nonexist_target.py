import re

from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlockdevSnapshotNonexistTarget(BlockDevSnapshotTest):
    def run_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        try:
            self.create_snapshot()
        except QMPCmdError as e:
            qmp_error_msg = self.params.get("qmp_error_msg")
            if not re.search(qmp_error_msg, str(e.data)):
                self.test.fail(str(e))
        else:
            self.test.fail("Create snapshot on a non-existed target node")


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with system disk
    2) do snapshot to a non-exist target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    snapshot_nonexist_target = BlockdevSnapshotNonexistTarget(test, params, env)
    snapshot_nonexist_target.run_test()
