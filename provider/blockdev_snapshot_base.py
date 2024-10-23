import logging

from virttest import data_dir, qemu_storage, utils_disk
from virttest.qemu_capabilities import Flags

from provider import backup_utils
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockDevSnapshotTest(object):
    def __init__(self, test, params, env):
        self.env = env
        self.test = test
        self.params = params
        self.snapshot_tag = params["snapshot_tag"]
        self.base_tag = params["base_tag"]
        self.disks_info = {}  # {tag, [dev, mnt]}
        self.files_info = list()
        self.main_vm = self.prepare_main_vm()
        self.clone_vm = self.prepare_clone_vm()
        self.snapshot_image = self.get_image_by_tag(self.snapshot_tag)
        self.base_image = self.get_image_by_tag(self.base_tag)

    def is_blockdev_mode(self):
        return self.main_vm.check_capability(Flags.BLOCKDEV)

    def prepare_main_vm(self):
        return self.env.get_vm(self.params["main_vm"])

    def prepare_clone_vm(self):
        vm_params = self.main_vm.params.copy()
        images = self.main_vm.params["images"].replace(self.base_tag, self.snapshot_tag)
        vm_params["images"] = images
        return self.main_vm.clone(params=vm_params)

    def get_image_by_tag(self, name):
        image_dir = data_dir.get_data_dir()
        image_params = self.params.object_params(name)
        return qemu_storage.QemuImg(image_params, image_dir, name)

    def prepare_snapshot_file(self):
        if self.is_blockdev_mode():
            params = self.params.copy()
            params.setdefault("target_path", data_dir.get_data_dir())
            image = sp_admin.volume_define_by_params(self.snapshot_tag, params)
            image.hotplug(self.main_vm)
        else:
            if self.params.get("mode") == "existing":
                self.snapshot_image.create()

    def mount_data_disks(self):
        if self.params["os_type"] == "windows":
            return
        session = self.clone_vm.wait_for_login()
        try:
            backup_utils.refresh_mounts(self.disks_info, self.params, session)
            for info in self.disks_info.values():
                disk_path = info[0]
                mount_point = info[1]
                utils_disk.mount(disk_path, mount_point, session=session)
        finally:
            session.close()

    def verify_data_file(self):
        for info in self.files_info:
            mount_point, filename = info[0], info[1]
            backup_utils.verify_file_md5(self.clone_vm, mount_point, filename)

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        if self.is_blockdev_mode():
            self.snapshot_image.base_tag = self.base_tag
            self.snapshot_image.base_format = self.base_image.get_format()
            base_image_filename = self.base_image.image_filename
            self.snapshot_image.base_image_filename = base_image_filename
            self.snapshot_image.rebase(self.snapshot_image.params)
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        if self.base_tag != "image1":
            self.mount_data_disks()
            self.verify_data_file()

    def create_snapshot(self):
        if self.is_blockdev_mode():
            options = ["node", "overlay"]
            cmd = "blockdev-snapshot"
        else:
            options = ["device", "mode", "snapshot-file", "format"]
            cmd = "blockdev-snapshot-sync"
        arguments = self.params.copy_from_keys(options)
        if not self.is_blockdev_mode():
            arguments["snapshot-file"] = self.snapshot_image.image_filename
        else:
            arguments.setdefault("overlay", "drive_%s" % self.snapshot_tag)
        return self.main_vm.monitor.cmd(cmd, dict(arguments))

    @staticmethod
    def get_linux_disk_path(session, disk_size):
        disks = utils_disk.get_linux_disks(session, True)
        for kname, attr in disks.items():
            if attr[1] == disk_size and attr[2] == "disk":
                return kname
        return None

    def configure_data_disk(self):
        os_type = self.params["os_type"]
        disk_params = self.params.object_params(self.base_tag)
        disk_size = disk_params["image_size"]
        session = self.main_vm.wait_for_login()
        try:
            if os_type != "windows":
                disk_id = self.get_linux_disk_path(session, disk_size)
                assert disk_id, "Disk not found in guest!"
                mount_point = utils_disk.configure_empty_linux_disk(
                    session, disk_id, disk_size
                )[0]
                self.disks_info[self.base_tag] = [r"/dev/%s1" % disk_id, mount_point]
            else:
                disk_id = utils_disk.get_windows_disks_index(session, disk_size)
                driver_letter = utils_disk.configure_empty_windows_disk(
                    session, disk_id, disk_size
                )[0]
                mount_point = r"%s:\\" % driver_letter
                self.disks_info[self.base_tag] = [disk_id, mount_point]
        finally:
            session.close()

    def generate_tempfile(self, root_dir, filename="data", size="10M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def snapshot_test(self):
        self.create_snapshot()
        for info in self.disks_info.values():
            self.generate_tempfile(info[1])
        self.verify_snapshot()

    def pre_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        if self.base_tag != "image1":
            self.configure_data_disk()
        self.prepare_snapshot_file()

    def post_test(self):
        try:
            self.clone_vm.destroy()
            self.snapshot_image.remove()
        except Exception as error:
            LOG_JOB.error(str(error))

    def run_test(self):
        self.pre_test()
        try:
            self.snapshot_test()
        finally:
            self.post_test()
