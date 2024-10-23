from virttest import utils_misc

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitHotunplug(BlockDevCommitTest):
    def is_device_deleted(self, device):
        return device not in str(self.main_vm.monitor.info_block())

    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["commit_speed"]
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        self.main_vm.monitor.cmd("device_del", {"id": self.params["device_tag"]})
        unplug_s = utils_misc.wait_for(
            lambda: self.is_device_deleted(device), timeout=60, step=1.0
        )
        if not unplug_s:
            self.test.fail("Hotunplug device failed")
        job_id = args.get("job-id", device)
        job_status = job_utils.get_job_status(self.main_vm, job_id)
        if job_status not in self.params["expect_status"]:
            self.test.fail("Job status %s is not correct" % job_status)
        self.main_vm.monitor.cmd("block-job-set-speed", {"device": job_id, "speed": 0})
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Hotunplug during block commit

    1. boot guest with data disk
    2. do live commit
    3. hotunplug data disk and check disk status
    3. check block job status
    4. check if the block job is completed
    """

    block_test = BlockdevCommitHotunplug(test, params, env)
    block_test.run_test()
