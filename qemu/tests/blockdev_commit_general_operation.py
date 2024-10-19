from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitGeneralOperation(BlockDevCommitTest):
    def commit_op(self, cmd, args=None):
        self.main_vm.monitor.cmd(cmd, args)
        job_status = job_utils.query_block_jobs(self.main_vm)
        self.test.log.info("The status after operation %s is %s", cmd, job_status)

    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["speed", "auto-finalize", "auto-dismiss"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["commit_speed"]
        arguments["auto-finalize"] = self.params.get_boolean("finalize")
        arguments["auto-dismiss"] = self.params.get_boolean("dismiss")
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": job_id, "speed": 10240}
        )
        self.commit_op("stop")
        self.commit_op("cont")
        self.commit_op("job-pause", {"id": job_id})
        self.commit_op("job-resume", {"id": job_id})
        self.commit_op("job-cancel", {"id": job_id})
        event = job_utils.get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_CANCELLED",
            self.params.get_numeric("job_cancelled_timeout", 60),
            device=job_id,
        )
        if event is None:
            self.test.fail("Job failed to cancel")
        if not self.params.get_boolean("dismiss"):
            self.commit_op("job-dismiss", {"id": job_id})
        self.main_vm.monitor.cmd(cmd, args)
        self.main_vm.monitor.cmd("block-job-set-speed", {"device": job_id, "speed": 0})
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)


def run(test, params, env):
    """
    Block commit general operation
    (both "auto-finalize"/"auto-dismiss" enabled and disabled)

    1. boot guest with data disk
    2. do live commit with different option
    3. do general operation during live commit
    """

    block_test = BlockdevCommitGeneralOperation(test, params, env)
    block_test.run_test()
