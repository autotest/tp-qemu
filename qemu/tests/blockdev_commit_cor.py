from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitCOR(BlockDevCommitTest):
    def create_snapshots(self, snapshot_tags, device):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        tag = snapshot_tags[0]
        params = self.params.object_params(tag)
        arguments = params.copy_from_keys(options)
        arguments["overlay"] = self.get_node_name(tag)
        fmt_node = self.main_vm.devices.get_by_qid(self.device_node)[0]
        self.base_node = fmt_node.get_param("file")
        arguments["node"] = self.base_node
        self.main_vm.monitor.cmd(cmd, dict(arguments))
        for info in self.disks_info:
            if device in info:
                self.generate_tempfile(info[1], tag)

    def commit_snapshots(self):
        device_tag = self.params["device_tag"].split()[0]
        device = self.get_node_name(device_tag)
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        job_id = args.get("job-id", device)
        self.main_vm.monitor.cmd(cmd, args)
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)


def run(test, params, env):
    """
    Block commit with copy-on-read filter on top

    1. boot guest with data disk
    2. create snapshot with copy-on-read filter on top
    3. commit snapshot to base with copy-on-read filter on top
    4. verify file's md5 after commit
    """

    block_test = BlockdevCommitCOR(test, params, env)
    block_test.run_test()
