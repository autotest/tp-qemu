import math
import random
import logging

from avocado.core import exceptions
from avocado.utils import memory

from virttest import data_dir
from virttest import env_process
from virttest import qemu_storage
from virttest import error_context
from virttest import utils_disk
from virttest import utils_numeric

from provider import backup_utils
from provider.virt_storage.storage_admin import sp_admin


def generate_random_cluster_size(blacklist):
    """
    generate valid value for cluster size
    :param blacklist: black list of cluster_size value
    :return: int type valid cluster size
    """
    if blacklist is None:
        blacklist = list()
    cluster_size = list(
        filter(
            lambda x: math.log2(x).is_integer(),
            range(
                512,
                2097152,
                1)))
    pool = set(cluster_size) - set(blacklist)
    return random.choice(list(pool))


def generate_tempfile(vm, root_dir, filename, size="10M", timeout=720):
    """Generate temp data file in VM"""
    session = vm.wait_for_login()
    if vm.params["os_type"] == "windows":
        file_path = "%s\\%s" % (root_dir, filename)
        mk_file_cmd = "fsutil file createnew %s %s" % (file_path, size)
        md5_cmd = "certutil -hashfile %s MD5 > %s.md5" % (file_path, file_path)
    else:
        file_path = "%s/%s" % (root_dir, filename)
        size_str = int(
            utils_numeric.normalize_data_size(
                size,
                order_magnitude="K",
                factor=1024))
        count = size_str // 4
        mk_file_cmd = "dd if=/dev/urandom of=%s bs=4k count=%s oflag=direct" % (
            file_path, count)
        md5_cmd = "md5sum %s > %s.md5 && sync" % (file_path, file_path)
    try:
        session.cmd(mk_file_cmd, timeout=timeout)
        session.cmd(md5_cmd, timeout=timeout)
    finally:
        session.close()


def verify_file_md5(vm, root_dir, filename, timeout=720):
    if vm.params["os_type"] == "windows":
        file_path = "%s\\%s" % (root_dir, filename)
        md5_cmd = "certutil -hashfile %s MD5" % file_path
        cat_cmd = "type %s.md5" % file_path
    else:
        file_path = "%s/%s" % (root_dir, filename)
        md5_cmd = "md5sum %s" % file_path
        cat_cmd = "cat %s.md5" % file_path

    session = vm.wait_for_login()
    try:
        status1, output1 = session.cmd_status_output(md5_cmd, timeout=timeout)
        now = output1.strip()
        if status1 != 0:
            raise exceptions.TestFail("Get '%s' MD5 with error: %s" % output1)
        status2, output2 = session.cmd_status_output(cat_cmd, timeout=timeout)
        saved = output2.strip()
        if status2 != 0:
            raise exceptions.TestFail("Read MD5 file with error: %s" % output2)
        assert now == saved, "File's ('%s') MD5 is mismatch! (%s, %s)" % (
            filename, now, saved)
    finally:
        session.close()


class BlockdevBackupSimpleTest(object):

    def __init__(self, test, params, env, source, target):
        self.main_vm = None
        self.clone_vm = None
        self.env = env
        self.test = test
        self.params = params
        self.backup_options = self.__get_backup_options(params)
        self.source_disk = self.__source_disk_define_by_params(params, source)
        self.target_disk = self.__target_disk_define_by_params(params, target)
        self._disk_entry = None
        self._data_dir = None
        self._tmp_dir = data_dir.get_tmp_dir()

    def __get_backup_options(self, params):
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
        if params.get("random_cluster_size") == "yes":
            blacklist = list(
                map(int, params.objects("cluster_size_blacklist")))
            cluster_size = generate_random_cluster_size(blacklist)
            image_params["image_cluster_size"] = cluster_size
            logging.info(
                "set source image cluster size to '%s'" %
                cluster_size)
        return qemu_storage.QemuImg(image_params, images_dir, image_name)

    def __source_disk_define_by_params(self, params, image_name):
        return self.__disk_define_by_params(params, image_name)

    def __target_disk_define_by_params(self, params, image_name):
        if params.get("random_cluster_size") == "yes":
            blacklist = list(
                map(int, params.objects("cluster_size_blacklist")))
            cluster_size = generate_random_cluster_size(blacklist)
            params["image_cluster_size"] = cluster_size
            logging.info(
                "set target image cluster size to '%s'" %
                cluster_size)
        return sp_admin.volume_define_by_params(image_name, params)

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
        self.format_data_disk_disk()
        generate_tempfile(self.main_vm, self._data_dir, "data")

    def prepare_clone_vm(self):
        """Boot VM with target data disk for verify purpose"""
        clone_params = self.main_vm.params.copy()
        images = clone_params["images"]
        clone_params["images"] = images.replace(
            self.source_disk.tag, self.target_disk.name)
        clone_vm = self.main_vm.clone(params=clone_params)
        clone_vm.create()
        clone_vm.verify_alive()
        if self.params["os_type"] != "windows":
            session = clone_vm.wait_for_login()
            try:
                logging.debug("mount target disk in VM!")
                utils_disk.mount(
                    self._disk_entry,
                    self._data_dir,
                    session=session)
            finally:
                session.close()
        self.clone_vm = clone_vm

    @error_context.context_aware
    def format_data_disk_disk(self):
        session = self.main_vm.wait_for_login()
        try:
            os_type = self.params["os_type"]
            disk_params = self.params.object_params(self.source_disk.tag)
            disk_size = disk_params["image_size"]
            if os_type == "windows":
                disk_id = utils_disk.get_windows_disks_index(session, disk_size)[
                    0]
                driver_letter = utils_disk.configure_empty_windows_disk(
                    session, disk_id, disk_size)[0]
                self._disk_entry = "%s:\\" % driver_letter
                self._data_dir = self._disk_entry
                return self._disk_entry
            else:
                disks = utils_disk.get_linux_disks(session, True)
                for kname, attr in disks.items():
                    if attr[1] == disk_size and attr[2] == "disk":
                        disk_id = kname
                        break
                else:
                    raise exceptions.TestFail("disk not found in guest ...")
                self._disk_entry = "/dev/%s1" % kname
                self._data_dir = utils_disk.configure_empty_linux_disk(
                    session, disk_id, disk_size)[0]
                return self._data_dir
        finally:
            session.close()

    @error_context.context_aware
    def prepare_source_disk(self):
        """create and format source disk by params"""
        params = self.params.object_params(self.source_disk.tag)
        self.source_disk.create(params)

    @error_context.context_aware
    def prepare_target_disk(self):
        """Hot add target disk to VM with qmp monitor"""
        error_context.context("Create target disk")
        self.target_disk.hotplug(self.main_vm)

    def prepare_test(self):
        self.prepare_source_disk()
        self.prepare_main_vm()
        self.prepare_target_disk()

    @error_context.context_aware
    def do_backup(self):
        """
        Backup source image to target image

        :param params: test params
        :param source_img: source image name or tag
        :param target_img: target image name or tag
        """

        source_name = "drive_%s" % self.source_disk.tag
        target_name = "drive_%s" % self.target_disk.name
        error_context.context("backup %s to %s, options: %s" %
                              (self.source_disk.tag, self.target_disk.name,
                                  self.backup_options))
        self.main_vm.reboot()
        try:
            backup_utils.full_backup(
                self.main_vm,
                source_name,
                target_name,
                **self.backup_options)
        finally:
            memory.drop_caches()
            self.main_vm.destroy()
        self.verify_target_disk()

    def verify_target_disk(self):
        """Verify file in target disk same with file in source disk"""
        self.prepare_clone_vm()
        try:
            verify_file_md5(self.clone_vm, self._data_dir, "data")
        finally:
            self.clone_vm.destroy()

    def post_test(self):
        try:
            self.source_disk.info(force_share=True)
            target_disk = self.__disk_define_by_params(
                self.params, self.target_disk.name)
            target_disk.info(force_share=True)
            images_dir = data_dir.get_data_dir()
            image_params = self.params.object_params(target_disk.tag)
            target_disk.check_image(image_params, images_dir, force_share=True)
        finally:
            self.source_disk.remove()
            sp_admin.remove_volume(self.target_disk)
            memory.drop_caches()

    def run_test(self):
        self.prepare_test()
        try:
            self.do_backup()
        finally:
            self.post_test()
