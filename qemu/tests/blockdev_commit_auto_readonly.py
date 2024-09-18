from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitAutoReadonly(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)


def run(test, params, env):
    """
    Block commit base Test

    1). boot guest with system disk
    2). create 2 snapshots and save file in each snapshot
    3). commit from sn2 to base
    4). verify files's md5
    """

    block_test = BlockdevCommitAutoReadonly(test, params, env)
    block_test.run_test()
