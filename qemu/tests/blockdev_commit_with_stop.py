from avocado.utils import process

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitWithStop(BlockDevCommitTest):
    def generate_tempfile(self, root_dir, filename="data", size="1000M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def commit_snapshots(self):
        device = self.params["device_tag"].split()[0]
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        device = self.get_node_name(snapshot_tags[-1])
        arguments = {"on-error": "stop"}
        cmd, arguments = backup_utils.block_commit_qmp_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, arguments)
        timeout = self.params.get("job_timeout", 600)
        self.main_vm.monitor.cmd(cmd, arguments)
        job_id = arguments.get("job-id", device)
        job_utils.wait_until_job_status_match(self.main_vm, "paused", job_id, timeout)
        process.system(self.params["extend_backend_space"])
        process.system(self.params["resize_backend_size"])
        args = {"id": job_id}
        self.main_vm.monitor.cmd("job-resume", args)
        job_utils.wait_until_block_job_completed(self.main_vm, job_id, timeout)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit with io-error:stop

    1). create small space(less than 1G)
    2). start vm with 2G data disk on it
    3). create snapshot, dd 1G file on it.
    4). commit snapshot to base with param "io-error:stop"
    5). wait until commit job paused
    6). extend lvm to 3G
    7). resize lvm
    8). resume block job
    9). wait until commit job finished
    """

    block_test = BlockdevCommitWithStop(test, params, env)
    block_test.run_test()
