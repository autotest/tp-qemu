import os
import logging
from functools import partial

from avocado.utils import process

from virttest import error_context
from virttest import qemu_storage
from virttest import env_process
from virttest import data_dir
from virttest.utils_test import BackgroundTest
from virttest.utils_test import VMStress

from provider import backup_utils
from qemu.tests import block_copy


class FullBackupTest(block_copy.BlockCopy):

    def __init__(self, test, params, env, tag):
        super(FullBackupTest, self).__init__(test, params, env, tag)
        self.device = "drive_%s" % tag

    def init_data_disk(self):
        """Initialize the data disk"""
        status = process.system(
            "which virt-make-fs",
            shell=True,
            ignore_status=True)
        if status != 0:
            raise self.test.error("libguestfs-tools-c not installed")
        params = self.params.object_params(self.tag)
        self.source_img = qemu_storage.QemuImg(params, self.data_dir, self.tag)
        self.image_file = self.source_img.image_filename
        cmd = "export LIBGUESTFS_BACKEND=direct; "
        cmd += "virt-make-fs -v -F %s" % params["image_format"]
        cmd += " -s %s" % params["image_size"]
        cmd += " -t %s" % params["filesystem_type"]
        cmd += " /boot %s" % self.image_file
        process.system(cmd, shell=True, ignore_status=False)

    def get_vm(self):
        self.init_data_disk()
        self.params["start_vm"] = "yes"
        env_process.preprocess_vm(
            self.test,
            self.params,
            self.env,
            self.params.get("main_vm"))
        vm = self.env.get_vm(self.params["main_vm"])
        vm.verify_alive()
        return vm

    def do_full_backup(self, tag):
        """Do full backup"""
        backing_info = dict()
        params = self.params.object_params(tag)
        node_name, target = backup_utils.create_target_block_device(
            self.vm, params, backing_info)
        if not node_name:
            out = self.vm.monitor.query_jobs()
            self.test.fail("Create target device failed, %s" % out)
        options = dict()
        compress = self.params.get("compress", "no") == "yes"
        auto_dismiss = self.params.get("auto-dismiss", "no") == "yes"
        auto_finalize = self.params.get("auto-finalize", "no") == "yes"
        if compress:
            options["compress"] = compress
        if auto_dismiss:
            options["auto-dismiss"] = auto_dismiss
        if auto_finalize:
            options["auto-finalize"] = auto_finalize
        backup_utils.full_backup(
            self.vm, self.device, node_name, options, True)
        self.trash_files.append(target)
        self.backup_check(target)

    def backup_check(self, target):
        if self.vm and self.vm.is_alive():
            self.vm.destroy()
        self.source_img.compare_images(target, self.image_file)

    def async_test(self, func, args=None, kwargs=None):
        args = args if args else tuple()
        kwargs = kwargs if kwargs else dict()
        bg_test = BackgroundTest(func, args, kwargs)
        bg_test.start()
        self.processes.append(bg_test)

    def reset_vm(self):
        reboot_kwargs = {"method": "system_reset", "boot_check": False}
        self.async_test(self.reboot, kwargs=reboot_kwargs)

    def with_stress(self):
        stress_pkg_name = self.params.get(
            "stress_pkg_name", "stress-1.0.4.tar.gz")
        stress_root_dir = os.path.join(data_dir.get_deps_dir(), "stress")
        stress_file = os.path.join(stress_root_dir, stress_pkg_name)
        stress_type = self.params.get("stress_type", "stress")
        stress = VMStress(
            self.vm,
            stress_type,
            self.params,
            download_type="tarball",
            downloaded_file_path=stress_file)
        self.async(stress.load_stress_tool)


@error_context.context_aware
def run(test, params, env):
    """
    Differential Backup Test
    1). boot VM with 2G data disk
    2). create bitmap1, bitmap2 to track changes in data disk
    3). do full backup for data disk
    4). create file1 in data disk and track it with bitmap2
    5). create file2 in data disk and track it with bitmap3
    6). merge bitmap2 and bitmap3 to bitmap4
    7). create file3 in data disk and track it with bitmap5
    8). merge bitmap5 to bitmap4
    9). do incremental backup with bitmap4
    10). reset and remove all bitmaps

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image2")
    backup_test = FullBackupTest(test, params, env, tag)
    try:
        error_context.context("Initialize data disk", logging.info)
        before_backup = params.get("before_backup")
        if before_backup:
            getattr(backup_test, before_backup)()
        error_context.context("Do full backup", logging.info)
        backup_test.do_full_backup("full")
    finally:
        backup_test.clean()
