import logging
from functools import partial

from avocado.utils import memory
from virttest import qemu_monitor, utils_misc

from provider import backup_utils, blockdev_base

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevIncreamentalBackupTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncreamentalBackupTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.bitmaps = []
        self.rebase_targets = []
        for tag in params.objects("source_images"):
            image_params = params.object_params(tag)
            image_chain = image_params.objects("image_backup_chain")
            self.source_images.append("drive_%s" % tag)
            self.full_backups.append("drive_%s" % image_chain[0])
            self.inc_backups.append("drive_%s" % image_chain[1])
            self.bitmaps.append("bitmap_%s" % tag)
            inc_img_tag = image_chain[-1]
            inc_img_params = params.object_params(inc_img_tag)

            # rebase 'inc' image onto 'base' image, so inc's backing is base
            inc_img_params["image_chain"] = image_params["image_backup_chain"]
            inc_img = self.source_disk_define_by_params(inc_img_params, inc_img_tag)
            target_func = partial(inc_img.rebase, params=inc_img_params)
            self.rebase_targets.append(target_func)

    def get_granularity(self):
        granularity = self.params.get("granularity")
        if granularity == "random":
            blacklist = self.params.objects("granularity_blacklist")
            granularity = backup_utils.generate_log2_value(
                512, 2147483648, 1, blacklist
            )
        return granularity

    def do_full_backup(self):
        extra_options = {"sync": "full", "auto_disable_bitmap": False}
        if self.params.get("auto_dismiss") == "no":
            extra_options["auto_dismiss"] = False
            extra_options["auto_finalize"] = False
        granularity = self.get_granularity()
        if granularity is not None:
            extra_options["granularity"] = granularity
            LOG_JOB.info("bitmap granularity is '%s' ", granularity)
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.bitmaps,
            **extra_options,
        )

    def generate_inc_files(self):
        for tag in self.params.objects("source_images"):
            self.generate_data_file(tag)

    def do_incremental_backup(self):
        extra_options = {"sync": "incremental", "auto_disable_bitmap": False}
        if self.params.get("completion_mode") == "grouped":
            extra_options["completion_mode"] = "grouped"
        if self.params.get("negative_test") == "yes":
            extra_options["wait_job_complete"] = False
            # Unwrap blockdev_batch_backup to catch the exception
            backup_func = backup_utils.blockdev_batch_backup.__wrapped__
            try:
                backup_func(
                    self.main_vm,
                    self.source_images,
                    self.inc_backups,
                    self.bitmaps,
                    **extra_options,
                )
            except qemu_monitor.QMPCmdError as e:
                if self.params["error_msg"] not in str(e):
                    self.test.fail("Unexpect error: %s" % str(e))
            else:
                self.test.fail("expect incremental backup job(s) failed")
        else:
            backup_utils.blockdev_batch_backup(
                self.main_vm,
                self.source_images,
                self.inc_backups,
                self.bitmaps,
                **extra_options,
            )

    def rebase_target_disk(self):
        return utils_misc.parallel(self.rebase_targets)

    def prepare_clone_vm(self):
        self.main_vm.destroy()
        images = self.params["images"]
        clone_params = self.main_vm.params.copy()
        for tag in self.params.objects("source_images"):
            img_params = self.params.object_params(tag)
            image_chain = img_params.objects("image_backup_chain")
            images = images.replace(tag, image_chain[-1])
        clone_params["images"] = images
        clone_vm = self.main_vm.clone(params=clone_params)
        clone_vm.create()
        clone_vm.verify_alive()
        self.clone_vm = clone_vm

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()
        if self.params.get("negative_test") == "yes":
            return
        self.main_vm.destroy()
        self.rebase_target_disk()
        memory.drop_caches()
        self.verify_target_disk()

    def verify_target_disk(self):
        self.prepare_clone_vm()
        try:
            self.verify_data_files()
        finally:
            self.clone_vm.destroy()


def run(test, params, env):
    """
    Blockdev incremental backup test

    test steps:
        1. boot VM with one or two data disks
        2. make filesystem in data disks
        3. create file and save it md5sum in data disks
        4. add target disks for backup to VM via qmp commands
        5. do full backup
        6. create new files and save it md5sum in data disks
        7. do incremental backup
        8. destroy VM and rebase incremental backup image
        9. start VM with image in step8
        10. verify files in data disks not change

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncreamentalBackupTest(test, params, env)
    inc_test.run_test()
