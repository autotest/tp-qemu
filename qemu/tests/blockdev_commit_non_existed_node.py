import logging
import re

from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevCommitNonExistedNode(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        if self.params.get("none_existed_base"):
            arguments["base-node"] = self.params["none_existed_base"]
            device = self.get_node_name(snapshot_tags[-1])
            arguments["top-node"] = device
        if self.params.get("none_existed_top"):
            arguments["base-node"] = self.get_node_name(device)
            device = self.get_node_name(snapshot_tags[-1])
            arguments["top-node"] = self.params["none_existed_top"]
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        try:
            self.main_vm.monitor.cmd(cmd, args)
        except QMPCmdError as e:
            LOG_JOB.info("Error message is %s", e.data)
            qmp_error_msg = self.params.get("qmp_error_msg")
            if not re.search(qmp_error_msg, str(e.data)):
                self.test.fail("Error message not as expected")
        else:
            self.test.fail(
                "Block commit should fail with "
                "'Cannot find device= nor node_name=sn0'"
                ",but block commit succeeded unexpectedly"
            )

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit with base is an non-existed snapshot in snapshot chain

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. specify an non-existed snapshot sn0 in snapshot chain as base
    4. do live commit
    5. check QMPCmdError data
    """

    block_test = BlockdevCommitNonExistedNode(test, params, env)
    block_test.run_test()
