from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitThrottle(BlockDevCommitTest):
    def commit_snapshots(self):
        def _commit_snapshots(device, base_node=None, top_node=None):
            arguments = {}
            if base_node:
                arguments.update({"base-node": base_node})
            if top_node:
                arguments.update({"top-node": top_node})
            backup_utils.block_commit(self.main_vm, device, **arguments)

        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        device = self.get_node_name(snapshot_tags[-1])
        base_node = self.get_node_name(snapshot_tags[0])
        top_node = self.get_node_name(snapshot_tags[-2])
        _commit_snapshots(device, base_node, top_node)
        base_node = self.device_node
        _commit_snapshots(device, base_node)


def run(test, params, env):
    """
    Block commit to throttle node

    1. boot guest with data disk
    2. create 5 snapshots and save file in each snapshot
    3. commit from sn1 to sn4
    4. commit from sn5 to base(throttle node)
    """

    block_test = BlockdevCommitThrottle(test, params, env)
    block_test.run_test()
