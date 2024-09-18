import logging

from virttest import data_dir, error_context, utils_disk

from provider import backup_utils
from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotMultiDisksTest(BlockDevSnapshotTest):
    def __init__(self, test, params, env):
        self.source_disks = params["source_disks"].split()
        self.target_disks = params["target_disks"].split()
        self.snapshot_tag_list = params["snapshot_tag"].split()
        self.base_tag_list = params["base_tag"].split()
        super(BlockdevSnapshotMultiDisksTest, self).__init__(test, params, env)

    def prepare_clone_vm(self):
        vm_params = self.main_vm.params.copy()
        for snapshot_tag, base_tag in zip(self.snapshot_tag_list, self.base_tag_list):
            images = self.main_vm.params["images"].replace(
                self.base_tag, self.snapshot_tag
            )
        vm_params["images"] = images
        return self.main_vm.clone(params=vm_params)

    def configure_data_disk(self):
        self.params["os_type"]
        for snapshot_tag in self.snapshot_tag_list:
            session = self.main_vm.wait_for_login()
            try:
                info = backup_utils.get_disk_info_by_param(
                    snapshot_tag, self.params, session
                )
                assert info, "Disk not found in guest!"
                mount_point = utils_disk.configure_empty_linux_disk(
                    session, info["kname"], info["size"]
                )[0]
                self.disks_info[snapshot_tag] = [
                    r"/dev/%s1" % info["kname"],
                    mount_point,
                ]
            finally:
                session.close()

    def prepare_snapshot_file(self):
        for snapshot_tag in self.snapshot_tag_list:
            if self.is_blockdev_mode():
                params = self.params.copy()
                params.setdefault("target_path", data_dir.get_data_dir())
                image = sp_admin.volume_define_by_params(snapshot_tag, params)
                image.hotplug(self.main_vm)
            else:
                if self.params.get("mode") == "existing":
                    snapshot_image = self.get_image_by_tag(snapshot_tag)
                    snapshot_image.create()

    @error_context.context_aware
    def create_snapshot(self):
        error_context.context("do snaoshot on multi_disks", LOG_JOB.info)
        assert len(self.target_disks) == len(
            self.source_disks
        ), "No enough target disks define in cfg!"
        source_lst = list(map(lambda x: "drive_%s" % x, self.source_disks))
        target_lst = list(map(lambda x: "drive_%s" % x, self.target_disks))
        arguments = {}
        if len(source_lst) > 1:
            error_context.context("snapshot %s to %s " % (source_lst, target_lst))
            backup_utils.blockdev_batch_snapshot(
                self.main_vm, source_lst, target_lst, **arguments
            )
        else:
            error_context.context("snapshot %s to %s" % (source_lst[0], target_lst[0]))
            backup_utils.blockdev_snapshot(self.main_vm, source_lst[0], target_lst[0])

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        for snapshot_tag, base_tag in zip(self.snapshot_tag_list, self.base_tag_list):
            if self.is_blockdev_mode():
                snapshot_image = self.get_image_by_tag(snapshot_tag)
                base_image = self.get_image_by_tag(base_tag)
                snapshot_image.base_tag = base_tag
                snapshot_image.base_format = base_image.get_format()
                base_image_filename = base_image.image_filename
                snapshot_image.base_image_filename = base_image_filename
                snapshot_image.rebase(snapshot_image.params)
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        if self.base_tag != "image1":
            self.mount_data_disks()
            self.verify_data_file()

    def post_test(self):
        try:
            self.clone_vm.destroy()
            for snapshot_tag in self.snapshot_tag_list:
                snapshot_image = self.get_image_by_tag(snapshot_tag)
                snapshot_image.remove()
        except Exception as error:
            LOG_JOB.error(str(error))


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with two data disks
    2) create target disks with qmp command
    3) format data disks in guest
    4) do snapshot to target disks in transaction mode
    5) dd file on data disks
    6) shutdown VM
    7) boot VM with target disks
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.update(
        {
            "image_name_%s" % base_image: params["image_name"],
            "image_format_%s" % base_image: params["image_format"],
        }
    )
    snapshot_multi_disks = BlockdevSnapshotMultiDisksTest(test, params, env)
    snapshot_multi_disks.run_test()
