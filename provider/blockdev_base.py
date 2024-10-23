import logging

from avocado.core import exceptions
from avocado.utils import memory
from virttest import (
    data_dir,
    env_process,
    error_context,
    qemu_storage,
    utils_disk,
    utils_misc,
)
from virttest.qemu_capabilities import Flags

from provider import backup_utils, job_utils
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevBaseTest(object):
    def __init__(self, test, params, env):
        self.main_vm = None
        self.params = params
        self.test = test
        self.env = env
        self.disks_info = {}  # tag, [dev, mount_point]
        self.files_info = {}  # tag, [file]
        self._tmp_dir = data_dir.get_tmp_dir()
        self.trash = []

    def is_blockdev_mode(self):
        return self.main_vm.check_capability(Flags.BLOCKDEV)

    def disk_define_by_params(self, params, image_name):
        images_dir = data_dir.get_data_dir()
        image_params = params.object_params(image_name)
        img = qemu_storage.QemuImg(image_params, images_dir, image_name)
        return img

    def source_disk_define_by_params(self, params, image_name):
        img = self.disk_define_by_params(params, image_name)
        return img

    def target_disk_define_by_params(self, params, image_name):
        if params.get("random_cluster_size") == "yes":
            blacklist = list(map(int, params.objects("cluster_size_blacklist")))
            cluster_size = backup_utils.generate_random_cluster_size(blacklist)
            params["image_cluster_size"] = cluster_size
            LOG_JOB.info("set target image cluster size to '%s'", cluster_size)
        params.setdefault("target_path", data_dir.get_data_dir())
        vol = sp_admin.volume_define_by_params(image_name, params)
        return vol

    def preprocess_data_disks(self):
        for tag in self.params.objects("source_images"):
            params = self.params.object_params(tag)
            if params.get("random_cluster_size") == "yes":
                blacklist = list(map(int, params.objects("cluster_size_blacklist")))
                cluster_size = backup_utils.generate_random_cluster_size(blacklist)
                params["image_cluster_size"] = cluster_size
                LOG_JOB.info("set image cluster size to '%s'", cluster_size)
            disk = self.source_disk_define_by_params(params, tag)
            disk.create(params)
            self.trash.append(disk)

    def prepare_main_vm(self):
        for vm in self.env.get_all_vms():
            if vm.is_alive():
                vm.destroy()
        vm_name = self.params["main_vm"]
        vm_params = self.params.object_params(vm_name)
        env_process.preprocess_vm(self.test, vm_params, self.env, vm_name)
        main_vm = self.env.get_vm(vm_name)
        main_vm.create()
        main_vm.verify_alive()
        self.main_vm = main_vm

    def generate_data_file(self, tag, filename=None):
        """
        Generate tempfile in the image

        :param tag: image tag
        :param filename: temp filename
        """
        if not filename:
            filename = utils_misc.generate_random_string(4)
        params = self.params.object_params(tag)
        image_size = params.get("tempfile_size", "10M")
        timeout = params.get_numeric("create_tempfile_timeout", 720)
        backup_utils.generate_tempfile(
            self.main_vm, self.disks_info[tag][1], filename, image_size, timeout
        )

        if tag not in self.files_info:
            self.files_info[tag] = [filename]
        else:
            self.files_info[tag].append(filename)

    def prepare_data_disk(self, tag):
        """
        Make file system on the disk, then create temp file
        and save it md5sum.

        :param tag: image tag
        """
        if tag != "image1":
            self.format_data_disk(tag)
        self.generate_data_file(tag)

    def prepare_data_disks(self):
        """
        prepare all data disks
        """
        for tag in self.params.objects("source_images"):
            self.prepare_data_disk(tag)

    def verify_data_files(self):
        """
        Verify temp file's md5sum in all data disks
        """
        session = self.clone_vm.wait_for_login()
        try:
            backup_utils.refresh_mounts(self.disks_info, self.params, session)
            for tag, info in self.disks_info.items():
                if tag != "image1":
                    LOG_JOB.debug("mount target disk in VM!")
                    utils_disk.mount(info[0], info[1], session=session)
                for data_file in self.files_info[tag]:
                    backup_utils.verify_file_md5(self.clone_vm, info[1], data_file)
        finally:
            session.close()

    @error_context.context_aware
    def format_data_disk(self, tag):
        session = self.main_vm.wait_for_login()
        try:
            info = backup_utils.get_disk_info_by_param(tag, self.params, session)
            if info is None:
                raise exceptions.TestFail("disk not found in guest ...")
            disk_path = "/dev/%s1" % info["kname"]
            mount_point = utils_disk.configure_empty_linux_disk(
                session, info["kname"], info["size"]
            )[0]
            self.disks_info[tag] = [disk_path, mount_point]
        finally:
            session.close()

    @error_context.context_aware
    def add_target_data_disks(self):
        """Hot add target disk to VM with qmp monitor"""
        error_context.context("Create target disk")
        for tag in self.params.objects("source_images"):
            image_params = self.params.object_params(tag)
            for img in image_params.objects("image_backup_chain"):
                disk = self.target_disk_define_by_params(self.params, img)
                disk.hotplug(self.main_vm)
                self.trash.append(disk)

    def prepare_test(self):
        self.prepare_main_vm()
        self.prepare_data_disks()
        self.add_target_data_disks()

    def post_test(self):
        try:
            self.destroy_vms()
            self.clean_images()
        finally:
            memory.drop_caches()

    def destroy_vms(self):
        """
        Stop all VMs
        """
        for vm in self.env.get_all_vms():
            if vm.is_alive():
                vm.destroy()

    def run_test(self):
        self.prepare_test()
        try:
            self.do_test()
        finally:
            self.post_test()

    def do_test(self):
        raise NotImplementedError

    def clean_images(self):
        """
        Cleanup all data images
        """
        for img in set(self.trash):
            try:
                # A QemuImg object
                img.remove()
            except AttributeError:
                # A StorageVolume object
                sp_admin.remove_volume(img)
            except Exception as e:
                LOG_JOB.warning(str(e))

    def check_block_jobs_started(self, jobid_list, tmo=10):
        """
        Test failed if any block job failed to start
        """
        job_utils.check_block_jobs_started(self.main_vm, jobid_list, tmo)

    def check_block_jobs_running(self, jobid_list, tmo=200):
        """
        Test failed if any block job's offset never increased
        """
        job_utils.check_block_jobs_running(self.main_vm, jobid_list, tmo)

    def check_block_jobs_paused(self, jobid_list, tmo=50):
        """
        Test failed if any block job's offset changed
        """
        job_utils.check_block_jobs_paused(self.main_vm, jobid_list, tmo)
