from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitTop(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["base-node"] = self.get_node_name(device)
        device = self.get_node_name(snapshot_tags[-1])
        arguments["top-node"] = device
        backup_utils.block_commit(self.main_vm, device, **arguments)


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 4 to base
    4. verify files's md5 after commit
    """

    block_test = BlockdevCommitTop(test, params, env)
    block_test.run_test()
