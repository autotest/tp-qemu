import logging

from virttest import qemu_storage
from virttest import data_dir
from virttest import utils_disk
from virttest.qemu_capabilities import Flags

from provider import backup_utils

from provider.virt_storage.storage_admin import sp_admin


class BlockDevCommitTest(object):

    def __init__(self, test, params, env):
        self.env = env
        self.test = test
        self.params = params
        self.device_node = self.get_node_name(params["device_tag"])
        self.snapshot_tags = params.objects("snapshot_tags")
        self.disks_info = list()
        self.files_info = list()
        self.main_vm = self.prepare_main_vm()
        self.snapshot_images = list(
            map(self.get_image_by_tag, self.snapshot_tags))

    @staticmethod
    def get_node_name(tag):
        return "drive_%s" % tag

    def is_blockdev_mode(self):
        return self.main_vm.check_capability(Flags.BLOCKDEV)

    def prepare_main_vm(self):
        return self.env.get_vm(self.params["main_vm"])

    def get_image_by_tag(self, name):
        image_dir = data_dir.get_data_dir()
        image_params = self.params.object_params(name)
        return qemu_storage.QemuImg(image_params, image_dir, name)

    def prepare_snapshot_file(self):
        if self.is_blockdev_mode():
            params = self.params.copy()
            params.setdefault("target_path", data_dir.get_data_dir())
            for tag in self.snapshot_tags:
                image = sp_admin.volume_define_by_params(tag, params)
                image.hotplug(self.main_vm)
        else:
            if self.params.get("mode") == "existing":
                for image in self.snapshot_images:
                    image.create()

    def mount_data_disks(self):
        if self.params["os_type"] == "windows":
            return
        session = self.clone_vm.wait_for_login()
        try:
            for info in self.disks_info:
                disk_path = info[0]
                mount_point = info[1]
                utils_disk.mount(disk_path, mount_point, session=session)
        finally:
            session.close()

    def verify_data_file(self):
        for idx, tag in enumerate(self.snapshot_tags):
            for info in self.files_info:
                mount_point, filename = info[0], info[1]
                backup_utils.verify_file_md5(
                    self.main_vm, mount_point, filename)

    def create_snapshots(self):
        if self.is_blockdev_mode():
            options = ["node", "overlay"]
            cmd = "blockdev-snapshot"
        else:
            options = ["device", "mode", "snapshot-file", "format"]
            cmd = "blockdev-snapshot-sync"
        for idx, tag in enumerate(self.snapshot_tags):
            params = self.params.object_params(tag)
            arguments = params.copy_from_keys(options)
            if not self.is_blockdev_mode():
                arguments["snapshot-file"] = self.snapshot_images[idx].image_filename
                arguments["device"] = self.device_node
            else:
                arguments["overlay"] = self.get_node_name(tag)
                if idx == 0:
                    arguments["node"] = self.device_node
                else:
                    arguments["node"] = self.get_node_name(
                        self.snapshot_tags[idx - 1])
            self.main_vm.monitor.cmd(cmd, dict(arguments))
            for info in self.disks_info:
                self.generate_tempfile(info[1], tag)

    def commit_snapshots(self):
        if self.is_blockdev_mode():
            options = ["base-node", "top-node", "speed"]
            arguments = self.params.copy_from_keys(options)
            arguments["base-node"] = self.get_node_name(
                self.params["base_tag"])
            arguments["top-node"] = self.get_node_name(self.params["top_tag"])
            device = self.get_node_name(self.snapshot_tags[-1])
        else:
            options = ["base", "top", "speed"]
            arguments = self.params.copy_from_keys(options)
            base_image = self.get_image_by_tag(self.params["base_tag"])
            top_image = self.get_image_by_tag(self.params['top_tag'])
            arguments["base"] = base_image.image_filename
            arguments["top"] = top_image.image_filename
            device = self.device_node
        backup_utils.block_commit(self.main_vm, device, **arguments)

    @staticmethod
    def get_linux_disk_path(session, disk_size):
        disks = utils_disk.get_linux_disks(session, True)
        for kname, attr in disks.items():
            if attr[1] == disk_size and attr[2] == "disk":
                return kname
        return None

    def configure_data_disk(self):
        os_type = self.params["os_type"]
        tag = self.params["device_tag"]
        disk_params = self.params.object_params(tag)
        disk_size = disk_params["image_size"]
        session = self.main_vm.wait_for_login()
        try:
            if os_type != "windows":
                disk_id = self.get_linux_disk_path(session, disk_size)
                assert disk_id, "Disk not found in guest!"
                mount_point = utils_disk.configure_empty_linux_disk(
                    session, disk_id, disk_size)[0]
                self.disks_info.append([
                    r"/dev/%s1" %
                    disk_id, mount_point])
            else:
                disk_id = utils_disk.get_windows_disks_index(
                    session, disk_size)
                driver_letter = utils_disk.configure_empty_windows_disk(
                    session, disk_id, disk_size)[0]
                mount_point = r"%s:\\" % driver_letter
                self.disks_info.append([disk_id, mount_point])
        finally:
            session.close()

    def generate_tempfile(self, root_dir, filename="data",
                          size="10M", timeout=360):
        backup_utils.generate_tempfile(
            self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def pre_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        self.configure_data_disk()
        self.prepare_snapshot_file()

    def post_test(self):
        try:
            self.main_vm.destroy()
            for image in self.snapshot_images:
                image.remove()
        except Exception as error:
            logging.error(str(error))

    def run_test(self):
        self.pre_test()
        try:
            self.create_snapshots()
            self.commit_snapshots()
            self.verify_data_file()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    6. verify files's md5
    """

    block_test = BlockDevCommitTest(test, params, env)
    block_test.run_test()
