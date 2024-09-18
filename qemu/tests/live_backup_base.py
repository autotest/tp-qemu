import logging
import re
import time

from avocado.utils import process
from virttest import qemu_storage, utils_misc
from virttest.staging import utils_memory

from qemu.tests import block_copy

LOG_JOB = logging.getLogger("avocado.test")


class LiveBackup(block_copy.BlockCopy):
    """
    Provide basic functions for live backup test cases.
    """

    def __init__(self, test, params, env, tag):
        """
        Init the default values for live backup object.

        :param test: Kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        :param tag: Image tag defined in parameter images
        """
        super(LiveBackup, self).__init__(test, params, env, tag)
        self.image_chain = self.params.get("image_chain").split()
        self.image_cmd = utils_misc.get_qemu_img_binary(params)
        self.source_image = self.params.get("source_image")
        self.speed = int(self.params.get("speed", 0))
        self.bitmap_name = "bitmap0"
        self.backup_index = 1
        self.backup_format = self.params.get("backup_format")
        self.generate_backup_params()
        self.full_backup_time = 0
        self.incremental_backup_time = 0

    def generate_backup_params(self):
        """
        Generate params for full backup image.
        """
        backup_params = self.params.object_params(self.source_image)
        backup_image = self.image_chain[0]
        for key, value in backup_params.items():
            if key not in ["image_name", "image_format"]:
                self.params["%s_%s" % (key, backup_image)] = value
        self.params["image_name_%s" % backup_image] = "images/%s" % backup_image
        self.params["image_format_%s" % backup_image] = self.backup_format

    def create_backup_image(self):
        """
        create backup image, with previous backup image as base image.
        :return: backupimage name
        """
        backup_image = self.image_chain[self.backup_index]
        backup_params = self.params.object_params(backup_image)
        backup_params["base_format"] = self.params.get("format")
        qemu_image = qemu_storage.QemuImg(backup_params, self.data_dir, backup_image)
        LOG_JOB.info("create backup image for %s", backup_image)
        backup_image_name, _ = qemu_image.create(backup_params)
        self.backup_index += 1
        self.trash_files.append(backup_image_name)
        return backup_image_name

    def create_backup(self, sync, backup_image_name=""):
        """
        create live backup with qmp command.
        """
        transaction = self.params.get("transaction", "yes")
        drive_name = self.get_device()
        bitmap_name = self.bitmap_name
        backup_format = self.backup_format
        speed = self.speed
        mode = "existing"
        if sync == "full":
            mode = "absolute-paths"
            granularity = int(self.params.get("granularity", 65536))
            backup_image_name = "images/%s.%s" % (self.image_chain[0], backup_format)
            backup_image_name = utils_misc.get_path(self.data_dir, backup_image_name)
            self.trash_files.append(backup_image_name)
            if transaction == "yes":
                args_list = []
                bitmap_args = {
                    "node": drive_name,
                    "name": bitmap_name,
                    "granularity": granularity,
                }
                self.transaction_add(args_list, "block-dirty-bitmap-add", bitmap_args)
                backup_args = {
                    "device": drive_name,
                    "target": backup_image_name,
                    "format": backup_format,
                    "sync": sync,
                    "mode": mode,
                    "speed": speed,
                }
                self.transaction_add(args_list, "drive-backup", backup_args)
                LOG_JOB.info(
                    "Create bitmap and drive-backup with transaction " "for %s",
                    drive_name,
                )
                self.vm.monitor.transaction(args_list)
                if not self.get_status():
                    self.test.fail("full backup job not found")
                return None

            LOG_JOB.info("Create bitmap for %s", drive_name)
            self.vm.monitor.operate_dirty_bitmap(
                "add", drive_name, bitmap_name, granularity
            )
        if not backup_image_name:
            self.test.error("No backup target provided.")
        LOG_JOB.info("Create %s backup for %s", sync, drive_name)
        self.vm.monitor.drive_backup(
            drive_name, backup_image_name, backup_format, sync, speed, mode, bitmap_name
        )
        if not self.get_status():
            self.test.fail("%s backup job not found" % sync)
        utils_memory.drop_caches()

    def transaction_add(self, args_list, type, data):
        """
        Generate a args list for a transaction.
        :param args_list: the arg_list param that will be modified
        :param type: type of the command
        :param data: data of the command
        """
        args = {"type": type, "data": data}
        args_list.append(args)

    def backup_check(self, compare_image=None):
        """
        Check and compare the backup images with qemu-img
        :param compare_image: the image that need to be compared
        """
        if self.vm and self.vm.is_alive():
            self.vm.destroy()
        data_dir = self.data_dir
        for image in self.image_chain:
            params = self.params.object_params(image)
            qemu_image = qemu_storage.QemuImg(params, data_dir, image)
            qemu_image.check_image(params, data_dir)
        params = self.params.object_params(self.source_image)
        if compare_image:
            compare_image = utils_misc.get_path(data_dir, compare_image)
            source_image = qemu_storage.storage.get_image_filename(params, data_dir)
            qemu_image.compare_images(compare_image, source_image)

    def get_image_size(self, image):
        """
        Get image size for given image.
        :param image: image file.
        :return: image size.
        """
        force_share = False
        pause_vm = False
        params = self.params.object_params(image)
        qemu_image = qemu_storage.QemuImg(params, self.data_dir, image)
        if self.vm:
            pids = process.getoutput(
                "lsof %s |grep -v PID|awk '{print $2}'" % qemu_image.image_filename
            )
            force_share = str(self.vm.get_pid()) in pids
            if force_share and not self.vm.is_paused():
                self.vm.pause()
                pause_vm = True
        image_info = qemu_image.info(force_share=force_share)
        if self.vm and pause_vm:
            self.vm.resume()
        if not image_info:
            self.test.error("Get image info failed.")
        image_size = re.findall(r"disk size: (\d\.?\d*?.*)", image_info)[0]
        image_size = int(float(utils_misc.normalize_data_size(image_size, "B")))
        LOG_JOB.info("Image size of %s is %s", image, image_size)
        return image_size

    def reopen(self):
        """
        Closing the vm and reboot it with the backup image.
        """
        image_chain = self.image_chain
        image_name = self.params.get("image_name_%s" % image_chain[-1])
        super(LiveBackup, self).reopen(image_name)

    def before_full_backup(self):
        """
        Run steps before create full backup.
        """
        return self.do_steps("before_full_backup")

    def before_incremental(self):
        """
        Run steps before create incremental backup.
        """
        return self.do_steps("before_incremental")

    def after_full_backup(self):
        """
        Run steps after create full backup.
        """
        self.full_backup_time = self.wait_for_finished()
        self.do_steps("after_full_backup")
        LOG_JOB.info("Sleep for guest data generation.")
        incremental_time = self.params.get("incremental_time", 120)
        time.sleep(incremental_time)

    def after_incremental(self):
        """
        Run steps after create incremental backup.
        """
        self.incremental_backup_time = self.wait_for_finished()
        return self.do_steps("after_incremental")

    def verify_job_info(self):
        """
        Check block job settings correctness.
        """
        params = self.params
        device_id = self.get_device()
        info = self.vm.monitor.info_block().get(device_id)
        check_params = params.get("check_params", "").split()
        check_params = filter(lambda x: x in params, check_params)
        for check_param in check_params:
            target_value = params[check_param]
            if check_param == "granularity":
                dirty_bitmap = info.get("dirty-bitmaps", "0")
                value = dirty_bitmap[0].get("granularity", "0")
            else:
                value = info.get(check_param, "")
            if str(value) != target_value:
                self.test.fail(
                    "%s unmatched. Target is %s, result is %s"
                    % (check_param, target_value, value)
                )

    def create_files(self):
        """
        Create files and record m5 values of them.
        """
        file_names = self.params["file_names"]
        return list(map(self.create_file, file_names.split()))

    def verify_md5s(self):
        """
        Check if the md5 values matches the record ones.
        """
        file_names = self.params["file_names"]
        return list(map(self.verify_md5, file_names.split()))

    def verify_efficiency(self):
        """
        Verify time and space efficiency for incremental backup.
        """
        if not self.incremental_backup_time < self.full_backup_time:
            self.test.fail(
                "incremental backup time %s, "
                "larger than full backup time %s "
                % (self.incremental_backup_time, self.full_backup_time)
            )
        LOG_JOB.info("Incremental backup time efficiency check passed.")
        full_size = self.get_image_size(self.image_chain[0])
        incre_size = self.get_image_size(self.image_chain[1])
        if incre_size > full_size:
            self.test.fail(
                "incremental backup image size %s, "
                "larger than full backup image size %s " % (incre_size, full_size)
            )
        LOG_JOB.info("Incremental backup space efficiency check passed.")
