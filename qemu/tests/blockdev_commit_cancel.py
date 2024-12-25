from avocado.utils import process

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockDevCommitCancel(BlockDevCommitTest):
    def generate_tempfile(self, root_dir, filename="data", size="1500M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def commit_snapshot(self):
        device = self.params.get_list("device_tag")[0]
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["base-node"] = self.get_node_name(device)
        arguments["top-node"] = self.get_node_name(snapshot_tags[-1])
        arguments["speed"] = self.params["speed"]
        device = self.get_node_name(snapshot_tags[-1])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        job_id = args.get("job-id", device)
        self.main_vm.monitor.cmd(cmd, args)
        if job_utils.is_block_job_running(self.main_vm, job_id):
            self.main_vm.monitor.cmd("block-job-cancel", {"device": job_id})
            event = job_utils.get_event_by_condition(
                self.main_vm,
                "BLOCK_JOB_CANCELLED",
                self.params.get_numeric("job_cancelled_timeout", 60),
                device=job_id,
            )
            if event is None:
                self.test.fail("Commit job failed to cancel")

    def check_backing_rw(self):
        base_image = self.get_image_by_tag(self.params["device_tag"])
        cmd = "lsof %s" % base_image.image_filename
        if "nbd" in base_image.image_filename:
            cmd = "lsof -i:%s" % self.params["nbd_port_%s" % self.params["device_tag"]]
        elif "rbd" in base_image.image_filename:
            cmd = "lsof -i:6800"
        output = process.run(cmd, verbose=True).stdout_text.split("\n")[1].split()
        pid, fd = (output[1], output[3][:-1])
        cmd = "cat /proc/%s/fdinfo/%s" % (pid, fd)
        output = process.run(cmd, verbose=True).stdout_text.split("\n")[1].split()[1]
        if output[-1] == "2":
            self.test.fail("backing image in rw status, should be in ro satus")

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshot()
            self.check_backing_rw()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    4. verify files's md5
    """

    block_test = BlockDevCommitCancel(test, params, env)
    block_test.run_test()
