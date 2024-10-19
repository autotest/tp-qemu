import random

from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitSpeedLimit(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["speed"]
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        job_utils.check_block_jobs_started(self.main_vm, [job_id])
        small_speed = self.params.get_numeric("small_speed")
        large_speed = self.params.get_numeric("large_speed")
        commit_speed = self.params.get(
            "commit_speed", random.randint(small_speed, large_speed)
        )
        if self.params.get_boolean("speed_is_int", True):
            commit_speed = int(commit_speed)
        try:
            self.main_vm.monitor.cmd(
                "block-job-set-speed", {"device": job_id, "speed": commit_speed}
            )
        except QMPCmdError as e:
            self.test.log.info("Error message is %s", e.data)
            if self.params.get("error_msg") not in str(e.data):
                self.test.fail("Error message not as expected")
        else:
            output = job_utils.query_block_jobs(self.main_vm)
            if output[0]["speed"] != commit_speed:
                self.test.fail("Commit speed set failed")
            self.main_vm.monitor.cmd(
                "block-job-set-speed", {"device": job_id, "speed": 0}
            )
            job_utils.wait_until_block_job_completed(self.main_vm, job_id)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit speed limit boundary test

    1. boot guest with data disk
    2. do block commit
    3. set commit speed to different value
    4. check the result of different commit speed
    """

    block_test = BlockdevCommitSpeedLimit(test, params, env)
    block_test.run_test()
