from virttest import env_process

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitHotunplug(BlockDevCommitTest):
    def commit_snapshot_and_destory_vm(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["commit_speed"]
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", device)
        job_utils.check_block_jobs_started(self.main_vm, [job_id])
        self.main_vm.destroy(gracefully=False)

    def boot_and_commit_snapshot(self):
        vm_name = self.params["main_vm"]
        vm_params = self.params.object_params(vm_name)
        images = self.params.objects("images")
        vm_params["images"] = " ".join(images)
        env_process.preprocess_vm(self.test, vm_params, self.env, vm_name)
        self.main_vm = self.env.get_vm(vm_name)
        self.pre_test()
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        device = self.get_node_name(snapshot_tags[-1])
        backup_utils.block_commit(self.main_vm, device, **arguments)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshot_and_destory_vm()
            self.boot_and_commit_snapshot()
            self.verify_data_file()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Hotunplug during block commit

    1. boot guest with data disk
    2. do live commit
    3. powerdown vm during live commit
    3. boot vm and do live commit again
    4. verify files's md5 after commit
    """

    block_test = BlockdevCommitHotunplug(test, params, env)
    block_test.run_test()
