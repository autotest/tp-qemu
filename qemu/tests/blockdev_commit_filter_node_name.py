from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitFilter(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["speed", "filter-node-name"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["commit_speed"]
        filter_node_name = self.params["filter_node_name"]
        arguments["filter-node-name"] = filter_node_name
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        block_info = self.main_vm.monitor.info_block()
        if filter_node_name not in block_info:
            self.test.fail(
                "Block info not correct,node-name should be '%s'" % filter_node_name
            )
        self.main_vm.monitor.cmd("block-job-set-speed", {"device": job_id, "speed": 0})
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)
        block_info = self.main_vm.monitor.info_block()
        if filter_node_name in block_info:
            self.test.fail(
                "Block info not correct,node-name should not"
                "be '%s'" % filter_node_name
            )


def run(test, params, env):
    """
    Block commit with filter-node-name set

    1. boot guest with data disk
    2. do live commit with filter-node-name option
    3. check block info during commit
    3. wait for block job completed
    4. check block info
    """

    block_test = BlockdevCommitFilter(test, params, env)
    block_test.run_test()
