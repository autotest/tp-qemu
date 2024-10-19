from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitStandby(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        job_utils.wait_until_job_status_match(
            self.main_vm, "ready", job_id, timeout=120
        )
        self.main_vm.monitor.cmd("job-pause", {"id": job_id})
        job_utils.wait_until_job_status_match(
            self.main_vm, "standby", job_id, timeout=120
        )
        self.main_vm.monitor.cmd("job-complete", {"id": job_id})
        self.main_vm.monitor.cmd("job-resume", {"id": job_id})
        if not job_utils.get_event_by_condition(self.main_vm, "BLOCK_JOB_COMPLETED"):
            self.test.fail("Block backup job not finished")


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with system disk
    2. create snapshot sn1 and save file in the snapshot
    3. commit snapshot sn1 to base
    4. when commit reach ready status, pause commit job
    5. complete the standby job
    6. resume the block job, wait until commit job finished
    """

    block_test = BlockdevCommitStandby(test, params, env)
    block_test.run_test()
