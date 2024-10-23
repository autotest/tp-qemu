from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitSpecifyNode(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        test_scenario = self.params["test_scenario"]
        if test_scenario == "base_same_with_top":
            arguments["base-node"] = self.get_node_name(snapshot_tags[-2])
            arguments["top-node"] = self.get_node_name(snapshot_tags[-2])
            device = self.get_node_name(snapshot_tags[-1])
        if test_scenario == "parent_as_top_child_as_base":
            arguments["base-node"] = self.get_node_name(snapshot_tags[-2])
            arguments["top-node"] = self.get_node_name(snapshot_tags[0])
            device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        try:
            self.main_vm.monitor.cmd(cmd, args)
        except QMPCmdError as e:
            self.test.log.info("Error message is %s", e.data)
            if self.params.get("error_msg") not in str(e.data):
                self.test.fail("Error message not as expected")
        else:
            self.test.fail(
                "Block commit should fail with %s,but "
                "block commit succeeded unexpectedly" % self.params.get("error_msg")
            )

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit with specified top and base node

    1. boot guest with data disk
    2. create snapshot and save file in snapshot
    3. specify node by test requirement
    4. do live commit
    5. check QMPCmdError data
    """

    block_test = BlockdevCommitSpecifyNode(test, params, env)
    block_test.run_test()
