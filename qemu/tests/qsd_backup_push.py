from functools import partial

from avocado.utils import memory
from virttest import error_context, utils_misc

from provider import backup_utils, blockdev_base
from provider.qsd import QsdDaemonDev


class QSDBackupTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(QSDBackupTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.bitmaps = []
        self.rebase_targets = []
        for tag in params.objects("source_images"):
            image_params = params.object_params(tag)
            image_chain = image_params.objects("image_backup_chain")
            self.source_images.append("fmt_%s" % tag)
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

    def get_qsd_demon(self):
        qsd_name = self.params["qsd_namespaces"]
        qsd_ins = QsdDaemonDev(qsd_name, self.params)
        return qsd_ins

    def start_qsd(self):
        self.qsd = self.get_qsd_demon()
        self.qsd.start_daemon()

    @error_context.context_aware
    def add_target_data_disks(self):
        """Hot add target disk via qsd monitor"""
        error_context.context("Create target disk")
        for tag in self.params.objects("source_images"):
            image_params = self.params.object_params(tag)
            for img in image_params.objects("image_backup_chain"):
                disk = self.target_disk_define_by_params(self.params, img)
                disk.hotplug(self.qsd)
                self.trash.append(disk)

    def do_full_backup(self):
        extra_options = {"sync": "full", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.qsd,
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
        backup_utils.blockdev_batch_backup(
            self.qsd,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options,
        )

    def rebase_target_disk(self):
        self.qsd.stop_daemon()
        return utils_misc.parallel(self.rebase_targets)

    def prepare_clone_vm(self):
        self.main_vm.destroy()
        images = self.params["images"]
        qsd_images = []
        clone_params = self.main_vm.params.copy()
        for tag in self.params.objects("source_images"):
            img_params = self.params.object_params(tag)
            image_chain = img_params.objects("image_backup_chain")
            images = images.replace(tag, image_chain[-1])
            qsd_images.append(image_chain[-1])
        self.params["qsd_images_qsd1"] = " ".join(qsd_images)
        clone_params["images"] = images
        clone_vm = self.main_vm.clone(params=clone_params)
        self.start_qsd()
        clone_vm.create()
        clone_vm.verify_alive()
        self.clone_vm = clone_vm

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()
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

    def prepare_test(self):
        self.start_qsd()
        super(QSDBackupTest, self).prepare_test()

    def post_test(self):
        super(QSDBackupTest, self).post_test()
        self.qsd.stop_daemon()


def run(test, params, env):
    """
    incremental backup test via qsd

     test steps:
        1. export data disk via qsd+nbd.
        2. boot VM with the exported data disk
        3. make filesystem in data disks
        4. create file and save it md5sum in data disks
        5. add backup images (base and inc) via qsd
        6. do full backup (stg1->base) via qsd monitor
        7. create new files and save it md5sum in data disks
        8. do incremental backup(stg1->inc) via qsd monitor
        9. destroy VM, stop qsd deamon, rebase inc to base
        10. export inc in step8 via qsd+nbd.
        11. start guest with the exported qsd image
        12. verify files in data disks not change

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = QSDBackupTest(test, params, env)
    inc_test.run_test()
