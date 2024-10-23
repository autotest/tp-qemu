import logging

from virttest import data_dir, error_context

from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotChainsTest(BlockDevSnapshotTest):
    def __init__(self, test, params, env):
        self.snapshot_num = int(params.get("snapshot_num", 1))
        self.snapshot_chains = []
        super(BlockdevSnapshotChainsTest, self).__init__(test, params, env)

    def prepare_snapshot_file(self):
        for index in range(self.snapshot_num + 1):
            snapshot_tag = "sn%s" % index
            if snapshot_tag not in self.snapshot_chains:
                self.snapshot_chains.append(snapshot_tag)
            params = self.params.copy()
            params.setdefault("target_path", data_dir.get_data_dir())
            params["image_size_%s" % snapshot_tag] = self.base_image.size
            params["image_name_%s" % snapshot_tag] = snapshot_tag
            self.params["image_name_%s" % snapshot_tag] = snapshot_tag
            snapshot_format = params.get("snapshot_format", "qcow2")
            params["image_format_%s" % snapshot_tag] = snapshot_format
            self.params["image_format_%s" % snapshot_tag] = snapshot_format
            if self.params["image_backend"] == "iscsi_direct":
                self.params.update({"enable_iscsi_%s" % snapshot_tag: "no"})
                self.params.update({"image_raw_device_%s" % snapshot_tag: "no"})
            elif self.params["image_backend"] == "ceph":
                self.params.update({"enable_ceph_%s" % snapshot_tag: "no"})
            elif self.params["image_backend"] == "nbd":
                self.params.update({"enable_nbd_%s" % snapshot_tag: "no"})
            image = sp_admin.volume_define_by_params(snapshot_tag, params)
            image.hotplug(self.main_vm)

    @error_context.context_aware
    def create_snapshot(self):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        arguments = self.params.copy_from_keys(options)
        for snapshot_tag in self.snapshot_chains:
            overlay = "drive_%s" % snapshot_tag
            arguments.update({"overlay": overlay})
            self.main_vm.monitor.cmd(cmd, dict(arguments))
            arguments["node"] = arguments["overlay"]

    def prepare_clone_vm(self):
        vm_params = self.params.copy()
        if not self.snapshot_chains:
            snapshot_tag = self.snapshot_tag
        else:
            snapshot_tag = self.snapshot_chains[-1]
        images = self.params["images"].replace(self.base_tag, snapshot_tag)
        vm_params["images"] = images
        return self.main_vm.clone(params=vm_params)

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        base_tag = self.base_tag
        base_format = self.base_image.get_format()
        self.params["image_format_%s" % base_tag] = base_format
        for snapshot_tag in self.snapshot_chains:
            snapshot_image = self.get_image_by_tag(snapshot_tag)
            base_image = self.get_image_by_tag(base_tag)
            snapshot_image.base_tag = base_tag
            snapshot_image.base_format = base_image.get_format()
            base_image_filename = base_image.image_filename
            snapshot_image.base_image_filename = base_image_filename
            snapshot_image.rebase(snapshot_image.params)
            base_tag = snapshot_tag
        self.clone_vm = self.prepare_clone_vm()
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        if self.base_tag != "image1":
            self.mount_data_disks()
            self.verify_data_file()

    def post_test(self):
        try:
            self.clone_vm.destroy()
            for snapshot_tag in self.snapshot_chains:
                snapshot_image = self.get_image_by_tag(snapshot_tag)
                snapshot_image.remove()
        except Exception as error:
            LOG_JOB.error(str(error))


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with data disk
    2) create target snapshot chains with qmp command
    3) do snapshot to snapshot nodes
    4) dd on top snapshot node
    5) shutdown VM
    6) boot VM with top snapshot node
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    snapshot_chains_test = BlockdevSnapshotChainsTest(test, params, env)
    snapshot_chains_test.run_test()
