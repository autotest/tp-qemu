import logging

from virttest import data_dir

from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotMergeTest(BlockDevSnapshotTest):
    def pre_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        if self.base_tag != "image1":
            self.configure_data_disk()

    def prepare_snapshot_file(self):
        self.params["image_size_%s" % self.snapshot_tag] = self.base_image.size
        self.params["image_name_%s" % self.snapshot_tag] = "images/" + self.snapshot_tag
        snapshot_format = self.params.get("snapshot_format", "qcow2")
        self.params["image_format_%s" % self.snapshot_tag] = snapshot_format
        if self.params["image_backend"] == "iscsi_direct":
            self.params.update({"enable_iscsi_%s" % self.snapshot_tag: "no"})
            self.params.update({"image_raw_device_%s" % self.snapshot_tag: "no"})
        elif self.params["image_backend"] == "ceph":
            self.params.update({"enable_ceph_%s" % self.snapshot_tag: "no"})
        elif self.params["image_backend"] == "nbd":
            self.params.update({"enable_nbd_%s" % self.snapshot_tag: "no"})
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        image = sp_admin.volume_define_by_params(self.snapshot_tag, params)
        image.hotplug(self.main_vm)
        return image

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy(free_mac_addresses=False)
        snapshot_tag = self.snapshot_tags[-1]
        for base_tag in self.snapshot_tags[-2::-1]:
            snapshot_image = self.get_image_by_tag(snapshot_tag)
            base_image = self.get_image_by_tag(base_tag)
            snapshot_image.base_tag = base_image.tag
            snapshot_image.base_format = base_image.get_format()
            base_image_filename = base_image.image_filename
            snapshot_image.base_image_filename = base_image_filename
            snapshot_image.rebase(snapshot_image.params)
            snapshot_image.commit()
            snapshot_tag = base_tag
        self.clone_vm = self.main_vm
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        if self.base_tag != "image1":
            self.mount_data_disks()
        self.verify_data_file()

    def snapshot_test(self):
        snapshot_nums = self.params.get_numeric("snapshot_num")
        self.snapshot_images = []
        self.snapshot_tags = [self.base_tag]
        for index in range(1, snapshot_nums + 1):
            self.snapshot_tag = "sn%s" % index
            if self.snapshot_tag not in self.snapshot_tags:
                self.snapshot_tags.append(self.snapshot_tag)
            snapshot_image = self.prepare_snapshot_file()
            self.snapshot_images.append(snapshot_image)

            self.params["overlay"] = "drive_%s" % self.snapshot_tag
            self.create_snapshot()
            self.params["node"] = self.params["overlay"]
            dd_filename = self.params.get("dd_filename") % index
            for info in self.disks_info.values():
                self.generate_tempfile(info[1], dd_filename)
        self.verify_snapshot()

    def post_test(self):
        try:
            self.clone_vm.destroy()
            for snapshot_image in self.snapshot_images:
                sp_admin.remove_volume(snapshot_image)
        except Exception as error:
            LOG_JOB.error(str(error))


def run(test, params, env):
    """
    Merge snapshot chain

    1) start VM with data disk
    2) create target disks with qmp command
    3) do snapshots, and create new file on every snapshot
    4) shutdown vm, rebase and commit snapshots to base
    5) start vm again, check files on data disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    snapshot_merge = BlockdevSnapshotMergeTest(test, params, env)
    snapshot_merge.run_test()
