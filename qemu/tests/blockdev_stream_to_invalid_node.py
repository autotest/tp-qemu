import random

from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlkdevStreamtoInvalidnode(BlockDevCommitTest):
    def commit_snapshots(self):
        device_tag = self.params.get("device_tag")
        device_params = self.params.object_params(device_tag)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device_tag)
        device = self.get_node_name(snapshot_tags[-1])
        backup_utils.block_commit(self.main_vm, device)

    def stream_to_invalid_node(self):
        snapshot_tags = self.params.get("snapshot_tags").split()
        stream_node_tag = random.choice(snapshot_tags)
        device_node = self.get_node_name(stream_node_tag)
        try:
            cmd, arguments = backup_utils.blockdev_stream_qmp_cmd(device_node)
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            qmp_error_msg = self.params.get("qmp_error_msg") % self.device_node
            if qmp_error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail("Can stream to an invalid node:%s" % device_node)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.stream_to_invalid_node()
        finally:
            self.post_test()


def run(test, params, env):
    """
 Block stream to an invalid node

    1. boot guest and create 4 snapshots and save file in each snapshot
    2. do block commit and wait for block job completed
    3. Random choice a node name in the snapshot chain, stream to it.
    """

    block_test = BlkdevStreamtoInvalidnode(test, params, env)
    block_test.run_test()
