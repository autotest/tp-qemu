import socket

from avocado.utils import process

from provider import backup_utils, job_utils, qemu_img_utils
from provider.blockdev_commit_base import BlockDevCommitTest
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevCommitFirewall(BlockDevCommitTest):
    def __init__(self, test, params, env):
        localhost = socket.gethostname()
        params["nbd_server_%s" % params["nbd_image_tag"]] = (
            localhost if localhost else "localhost"
        )
        self._offset = None
        self._net_down = False
        super(BlockdevCommitFirewall, self).__init__(test, params, env)

    def _export_local_image_with_nbd(self):
        self._nbd_export = QemuNBDExportImage(
            self.params, self.params["local_image_tag"]
        )
        self._nbd_export.create_image()
        self._nbd_export.export_image()

    def pre_test(self):
        try:
            self._export_local_image_with_nbd()
            boot_vm_cmd = qemu_img_utils.boot_vm_with_images
            self.main_vm = boot_vm_cmd(self.test, self.params, self.env)
            super(BlockdevCommitFirewall, self).pre_test()
        except:
            self.clean_images()

    def _run_iptables(self, cmd):
        cmd = cmd.format(s=self.params["nbd_server_%s" % self.params["nbd_image_tag"]])
        result = process.run(cmd, ignore_status=True, shell=True)
        if result.exit_status != 0:
            self.test.error("command error: %s" % result.stderr.decode())

    def break_net_with_iptables(self):
        self._run_iptables(self.params["net_break_cmd"])
        self._net_down = True

    def resume_net_with_iptables(self):
        self._run_iptables(self.params["net_resume_cmd"])
        self._net_down = False

    def clean_images(self):
        # recover nbd image access
        if self._net_down:
            self.resume_net_with_iptables()

        # stop nbd image export
        self._nbd_export.stop_export()

        # remove nbd image after test
        nbd_image = self.get_image_by_tag(self.params["local_image_tag"])
        nbd_image.remove()

    def generate_tempfile(self, root_dir, filename="data", size="1000M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        device = self.get_node_name(snapshot_tags[-1])
        options = ["speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["speed"]
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(device, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        self.job_id = args.get("job-id", device)

    def post_test(self):
        super(BlockdevCommitFirewall, self).post_test()
        self.clean_images()

    def run_test(self):
        self.pre_test()
        try:
            job_list = []
            self.commit_snapshots()
            job_list.append(self.job_id)
            job_utils.check_block_jobs_running(self.main_vm, job_list)
            self.break_net_with_iptables()
            job_utils.check_block_jobs_paused(self.main_vm, job_list)
            self.resume_net_with_iptables()
            job_utils.check_block_jobs_running(self.main_vm, job_list)
            job_utils.wait_until_block_job_completed(self.main_vm, self.job_id)
            self.verify_data_file()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit base Test

    1). boot guest with base:data disk whose backend is nbd or other
    2). create snapshot:sn1 and save file in it
    3). commit sn1 to base, check offset of block job changed
    4). during commit, set firewall to stop the connection
    5). check offset of block job not changed
    6). reset firewall to resume the connection
    7). check offset of block job changed and block job can be finished
    """
    block_test = BlockdevCommitFirewall(test, params, env)
    block_test.run_test()
