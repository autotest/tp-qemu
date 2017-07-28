import time

from virttest import utils_misc
from virttest import qemu_storage

from qemu.tests import live_backup_base


class LiveBackupMulti(live_backup_base.LiveBackup):
    def __init__(self, test, params, env, tag):
        """
        Init the default values for live backup object.

        :param test: Kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        :param tag: Image tag defined in parameter images
        """
        super(LiveBackupMulti, self).__init__(test, params, env, tag)
        self.vm = self.get_vm()
        self.bitmap_list = []
        self.bitmap_args_list = []
        self.full_backup_arg_list = []
        self.increm_backup_arg_list = []
        self.image_list = params.objects("images")
        self.image_chain_map = {}
        self.complete_count = 3
        self.generate_params()

    def image_chain_reassign(self, source_image):
        """
        Reassign the image chain according to the image given. Source image
        should be image given, and per self.image_chain_map{} update params
        "image_chain", which will be used for creating backup image.

        :param source_image: The source image of the backup chain.
        :return: Updated params set per source image given.
        """
        self.source_image = source_image
        self.params["image_chain"] = self.image_chain_map[source_image]
        image_params = self.params.object_params(source_image)
        self.image_chain = image_params.get("image_chain").split()
        return image_params

    def generate_params(self):
        """
        Generate params set for all images, including the image_chain and
        the transaction command lists for dirty bitmap and backup jobs.
        """
        for image in self.image_list:
            full_backup_image = "%sFullbackup" % image
            increm_backup_image = "%sIncremental0" % image
            self.params["image_name_%s" % increm_backup_image] = (
                "images/%s" % increm_backup_image)
            self.image_chain_map[image] = (
                "%s %s" % (full_backup_image, increm_backup_image))

            # generate params for full backup images.
            image_params = self.image_chain_reassign(image)
            self.generate_backup_params()

            # generate bitmap transaction args.
            image_file = qemu_storage.storage.get_image_filename(
                image_params, self.data_dir)
            drive_name = self.vm.get_block({"file": image_file})
            bitmap_name = "bitmap_%s" % image
            self.bitmap_list.append(bitmap_name)
            bitmap_args = {"node": drive_name, "name": bitmap_name}
            self.transaction_add(self.bitmap_args_list,
                                 "block-dirty-bitmap-add", bitmap_args)

            # generate full backup transaction args.
            backup_format = self.backup_format
            backup_image_name = "images/%s.%s" % (full_backup_image,
                                                  backup_format)
            backup_image_name = utils_misc.get_path(
                self.data_dir, backup_image_name)
            full_backup_args = {"device": drive_name,
                                "target": backup_image_name,
                                "format": backup_format,
                                "sync": "full"}
            self.transaction_add(self.full_backup_arg_list,
                                 "drive-backup", full_backup_args)

            # generate incremental backup transaction args.
            backup_image_name = "images/%s.%s" % (increm_backup_image,
                                                  backup_format)
            backup_image_name = utils_misc.get_path(
                self.data_dir, backup_image_name)
            backup_format = self.backup_format
            increm_backup_args = {"device": drive_name,
                                  "target": backup_image_name,
                                  "format": backup_format,
                                  "sync": "incremental",
                                  "mode": "existing",
                                  "bitmap": bitmap_name}
            self.transaction_add(self.increm_backup_arg_list,
                                 "drive-backup", increm_backup_args)

    def create_backup_images(self):
        """
        Create backup for all images.
        """
        for image in self.image_list:
            self.backup_index = 1
            self.image_chain_reassign(image)
            self.create_backup_image()

    def reboot_with_new_disks(self):
        """
        Reboot the guest with last backup images in the chain.
        """
        self.vm.destroy()
        for image in self.image_list:
            self.image_chain_reassign(image)
            image_chain = self.image_chain
            image_name = self.params.get("image_name_%s" %
                                         image_chain[len(image_chain) - 1])
            self.params["image_name_%s" % image] = image_name
            self.params["force_create_image_%s" % image] = "no"
        self.vm.create(params=self.params)
        self.mount_disks_linux()

    def backups_check(self, compare_image=None):
        """
        Check all backup images for multi blocks.
        """
        for image in self.image_list:
            self.image_chain_reassign(image)
            self.backup_check(compare_image)

    def is_complete(self):
        """
        Judgement for block job completed, 3 parallel block jobs need 3 event back.
        But for incremental backup, time is too short to catch all event, so need
        to set complet_count to 1.
        :return: bool value for completed or not.
        """
        monitor = self.vm.monitor
        i = 0
        while i < self.complete_count:
            if monitor.get_event("BLOCK_JOB_COMPLETED"):
                monitor.clear_event("BLOCK_JOB_COMPLETED")
                i += 1
            else:
                continue
        time.sleep(10)
        return True

    def set_complete_count(self, complete_count):
        """
        Set complete event count for is_completed().
        :param complete_count: complete event count
        """
        self.complete_count = complete_count


def run(test, params, env):
    """
    Multiple block backup test:
    1. Boot the VM in a paused state, and with 3 disks
    2. Format data disks
    3. Add bitmaps for each disk
    4. Create full backups for each disk within one transaction
    5. Create corresponding destination images for each incremental backup
    6. Create new files inside guest in each disk and record their md5
    7. Incremental backup all blocks with transaction
    8. Shutdown guest
    9. Boot guest with all incremental backup images.
    10. Check files create in step6 exists and md5 values consistent

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    backup_test = LiveBackupMulti(test, params, env, tag)
    try:
        backup_test.before_full_backup()
        backup_test.vm.monitor.transaction(backup_test.bitmap_args_list)
        backup_test.vm.monitor.transaction(backup_test.full_backup_arg_list)
        backup_test.after_full_backup()
        backup_test.create_backup_images()
        backup_test.before_incremental()
        backup_test.set_complete_count(1)
        backup_test.vm.monitor.transaction(backup_test.increm_backup_arg_list)
        backup_test.after_incremental()
    finally:
        backup_test.clean()
