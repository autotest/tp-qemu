import logging

from avocado.core import exceptions
from avocado.utils import memory
from virttest import (
    data_dir,
    env_process,
    error_context,
    qemu_storage,
    qemu_vm,
    utils_disk,
)
from virttest.qemu_capabilities import Flags

from provider import backup_utils
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevBackupBaseTest(object):
    def __init__(self, test, params, env):
        self.main_vm = None
        self.clone_vm = None
        self.env = env
        self.test = test
        self.params = params
        self.source_disks = params.objects("source_images")
        self.target_disks = params.objects("target_images")
        self.backup_options = self.get_backup_options(params)
        self.disks_info = dict()
        self._tmp_dir = data_dir.get_tmp_dir()

    def is_blockdev_mode(self):
        return self.main_vm.check_capability(Flags.BLOCKDEV)

    def get_backup_options(self, params):
        opts = params.objects("backup_options")
        extra_options = params.copy_from_keys(opts)
        for k, v in extra_options.items():
            if v in ("yes", "true"):
                extra_options[k] = True
            if v in ("no", "false"):
                extra_options[k] = False
        return extra_options

    def __disk_define_by_params(self, params, image_name):
        images_dir = data_dir.get_data_dir()
        image_params = params.object_params(image_name)
        return qemu_storage.QemuImg(image_params, images_dir, image_name)

    def __source_disk_define_by_params(self, params, image_name):
        return self.__disk_define_by_params(params, image_name)

    def __target_disk_define_by_params(self, params, image_name):
        if params.get("random_cluster_size") == "yes":
            blacklist = list(map(int, params.objects("cluster_size_blacklist")))
            cluster_size = backup_utils.generate_random_cluster_size(blacklist)
            params["image_cluster_size"] = cluster_size
            LOG_JOB.info("set target image cluster size to '%s'", cluster_size)
        params.setdefault("target_path", data_dir.get_data_dir())
        return sp_admin.volume_define_by_params(image_name, params)

    def preprocess_data_disks(self):
        for tag in self.source_disks:
            params = self.params.object_params(tag)
            if params.get("random_cluster_size") == "yes":
                blacklist = list(map(int, params.objects("cluster_size_blacklist")))
                cluster_size = backup_utils.generate_random_cluster_size(blacklist)
                params["image_cluster_size"] = cluster_size
                LOG_JOB.info("set image cluster size to '%s'", cluster_size)
            disk = self.__source_disk_define_by_params(params, tag)
            disk.create(params)

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

    def prepare_data_disks(self):
        for tag in self.source_disks:
            self.format_data_disk(tag)
            backup_utils.generate_tempfile(
                self.main_vm, self.disks_info[tag][1], "data"
            )

    def verify_data_files(self):
        session = self.clone_vm.wait_for_login()
        try:
            backup_utils.refresh_mounts(self.disks_info, self.params, session)
            for tag, info in self.disks_info.items():
                LOG_JOB.debug("mount target disk in VM!")
                utils_disk.mount(info[0], info[1], session=session)
                backup_utils.verify_file_md5(self.clone_vm, info[1], "data")
        finally:
            session.close()

    def prepare_clone_vm(self):
        """Boot VM with target data disk for verify purpose"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        clone_params = self.main_vm.params.copy()
        for idx in range(len(self.source_disks)):
            images = clone_params["images"]
            src_tag = self.source_disks[idx]
            dst_tag = self.target_disks[idx]
            clone_params["images"] = images.replace(src_tag, dst_tag)
        clone_vm = self.main_vm.clone(params=clone_params)
        clone_vm.create()
        clone_vm.verify_alive()
        self.clone_vm = clone_vm

    @error_context.context_aware
    def format_data_disk(self, tag):
        session = self.main_vm.wait_for_login()
        try:
            disk_params = self.params.object_params(tag)
            disk_size = disk_params["image_size"]
            disks = utils_disk.get_linux_disks(session, True)
            for kname, attr in disks.items():
                if attr[1] == disk_size and attr[2] == "disk":
                    disk_id = kname
                    break
            else:
                raise exceptions.TestFail("disk not found in guest ...")
            disk_path = "/dev/%s1" % kname
            mount_point = utils_disk.configure_empty_linux_disk(
                session, disk_id, disk_size
            )[0]
            self.disks_info[tag] = [disk_path, mount_point]
        finally:
            session.close()

    @error_context.context_aware
    def add_target_data_disks(self):
        """Hot add target disk to VM with qmp monitor"""
        error_context.context("Create target disk")
        for tag in self.target_disks:
            disk = self.__target_disk_define_by_params(self.params, tag)
            disk.hotplug(self.main_vm)

    def prepare_test(self):
        self.prepare_main_vm()
        self.prepare_data_disks()
        self.add_target_data_disks()

    @error_context.context_aware
    def blockdev_backup(self):
        assert len(self.target_disks) >= len(
            self.source_disks
        ), "No enough target disks define in cfg!"
        source_lst = list(map(lambda x: "drive_%s" % x, self.source_disks))
        target_lst = list(map(lambda x: "drive_%s" % x, self.target_disks))
        bitmap_lst = list(map(lambda x: "bitmap_%s" % x, range(len(self.source_disks))))
        try:
            if len(source_lst) > 1:
                error_context.context(
                    "backup %s to %s, options: %s"
                    % (source_lst, target_lst, self.backup_options)
                )
                backup_utils.blockdev_batch_backup(
                    self.main_vm,
                    source_lst,
                    target_lst,
                    bitmap_lst,
                    **self.backup_options,
                )
            else:
                error_context.context(
                    "backup %s to %s, options: %s"
                    % (source_lst[0], target_lst[0], self.backup_options)
                )
                backup_utils.blockdev_backup(
                    self.main_vm, source_lst[0], target_lst[0], **self.backup_options
                )
        finally:
            memory.drop_caches()

    @error_context.context_aware
    def do_backup(self):
        """
        Backup source image to target image

        :param params: test params
        :param source_img: source image name or tag
        :param target_img: target image name or tag
        """
        raise NotImplementedError

    def verify_target_disk(self):
        """Verify file in target disk same with file in source disk"""
        raise NotImplementedError

    def destroy_vms(self):
        for vm in [self.main_vm, self.clone_vm]:
            if not isinstance(vm, qemu_vm.VM):
                continue
            if vm.is_alive():
                vm.destroy()

    def cleanup_data_disks(self):
        images_dir = data_dir.get_data_dir()
        for tag in self.source_disks + self.target_disks:
            image_params = self.params.object_params(tag)
            disk = self.__disk_define_by_params(self.params, tag)
            disk.info(force_share=True)
            disk.check_image(image_params, images_dir, force_share=True)
            disk.remove()

    def post_test(self):
        try:
            self.destroy_vms()
            self.cleanup_data_disks()
        finally:
            memory.drop_caches()

    def run_test(self):
        self.prepare_test()
        try:
            self.do_backup()
        finally:
            self.post_test()
