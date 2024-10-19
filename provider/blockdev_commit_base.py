import logging

from virttest import data_dir, qemu_storage, utils_disk

from provider import backup_utils, job_utils
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockDevCommitTest(object):
    def __init__(self, test, params, env):
        self.env = env
        self.test = test
        self.params = params
        self.disks_info = list()
        self.files_info = list()
        self.main_vm = self.prepare_main_vm()

    @staticmethod
    def get_node_name(tag):
        return "drive_%s" % tag

    def prepare_main_vm(self):
        return self.env.get_vm(self.params["main_vm"])

    def get_image_by_tag(self, name):
        image_dir = data_dir.get_data_dir()
        image_params = self.params.object_params(name)
        return qemu_storage.QemuImg(image_params, image_dir, name)

    def prepare_snapshot_file(self, snapshot_tags):
        self.snapshot_images = list(map(self.get_image_by_tag, snapshot_tags))
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        for tag in snapshot_tags:
            image = sp_admin.volume_define_by_params(tag, params)
            image.hotplug(self.main_vm)

    def verify_data_file(self):
        for info in self.files_info:
            mount_point, filename = info[0], info[1]
            backup_utils.verify_file_md5(self.main_vm, mount_point, filename)

    def create_snapshots(self, snapshot_tags, device):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        for idx, tag in enumerate(snapshot_tags):
            params = self.params.object_params(tag)
            arguments = params.copy_from_keys(options)
            arguments["overlay"] = self.get_node_name(tag)
            if idx == 0:
                arguments["node"] = self.device_node
            else:
                arguments["node"] = self.get_node_name(snapshot_tags[idx - 1])
            self.main_vm.monitor.cmd(cmd, dict(arguments))
            for info in self.disks_info:
                if device in info:
                    self.generate_tempfile(info[1], tag)

    def commit_snapshots(self):
        job_id_list = []
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            options = ["base-node", "top-node", "speed"]
            arguments = self.params.copy_from_keys(options)
            arguments["base-node"] = self.get_node_name(device)
            arguments["top-node"] = self.get_node_name(snapshot_tags[-2])
            device = self.get_node_name(snapshot_tags[-1])
            if len(self.params["device_tag"].split()) == 1:
                backup_utils.block_commit(self.main_vm, device, **arguments)
            else:
                commit_cmd = backup_utils.block_commit_qmp_cmd
                cmd, args = commit_cmd(device, **arguments)
                backup_utils.set_default_block_job_options(self.main_vm, args)
                job_id = args.get("job-id", device)
                job_id_list.append(job_id)
                self.main_vm.monitor.cmd(cmd, args)
        for job_id in job_id_list:
            job_utils.wait_until_block_job_completed(self.main_vm, job_id)

    @staticmethod
    def get_linux_disk_path(session, disk_size):
        disks = utils_disk.get_linux_disks(session, True)
        for kname, attr in disks.items():
            if attr[1] == disk_size and attr[2] == "disk":
                return kname
        return None

    def configure_disk(self, tag):
        """
        support configuration on both system and data disk
        """
        if tag == self.params["images"].split()[0]:
            self.configure_system_disk(tag)
        else:
            self.configure_data_disk(tag)

    def configure_system_disk(self, tag):
        self.disks_info.append(["", self.params["mount_point"], tag])

    def configure_data_disk(self, tag):
        os_type = self.params["os_type"]
        disk_params = self.params.object_params(tag)
        disk_size = disk_params["image_size"]
        session = self.main_vm.wait_for_login()
        try:
            if os_type != "windows":
                disk_id = self.get_linux_disk_path(session, disk_size)
                assert disk_id, "Disk not found in guest!"
                mount_point = utils_disk.configure_empty_linux_disk(
                    session, disk_id, disk_size
                )[0]
                self.disks_info.append([r"/dev/%s1" % disk_id, mount_point, tag])
            else:
                disk_id = utils_disk.get_windows_disks_index(session, disk_size)
                driver_letter = utils_disk.configure_empty_windows_disk(
                    session, disk_id, disk_size
                )[0]
                mount_point = r"%s:\\" % driver_letter
                self.disks_info.append([disk_id, mount_point, tag])
        finally:
            session.close()

    def generate_tempfile(self, root_dir, filename="data", size="10M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def pre_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            self.configure_disk(device)
            self.prepare_snapshot_file(snapshot_tags)
            self.create_snapshots(snapshot_tags, device)

    def post_test(self):
        try:
            self.main_vm.destroy()
            for image in self.snapshot_images:
                image.remove()
        except Exception as error:
            LOG_JOB.error(str(error))

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.verify_data_file()
        finally:
            self.post_test()
