import ast
from functools import partial

from virttest import utils_misc

from provider import backup_utils, block_dirty_bitmap, blockdev_base


class BlockdevIncbkWithMigration(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncbkWithMigration, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.inc_backup_tags = []
        self.bitmaps = []
        self.bitmap_counts = {}
        self.rebase_funcs = []
        self.src_img_tags = params.objects("source_images")
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.inc_backups.append("drive_%s" % image_chain[1])
        self.inc_backup_tags.append(image_chain[1])
        self.bitmaps.append("bitmap_%s" % tag)
        self.bitmap_counts["bitmap_%s" % tag] = None

        # rebase 'inc' image onto 'base' image, so inc's backing is base
        inc_img_params = self.params.object_params(image_chain[1])
        inc_img_params["image_chain"] = image_params["image_backup_chain"]
        inc_img = self.source_disk_define_by_params(inc_img_params, image_chain[1])
        self.rebase_funcs.append(partial(inc_img.rebase, params=inc_img_params))

        # Only hotplug full backup images before full-backup
        self.params["image_backup_chain_%s" % tag] = image_chain[0]

    def do_full_backup(self):
        extra_options = {"sync": "full", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.bitmaps,
            **extra_options,
        )

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def do_incremental_backup(self):
        extra_options = {"sync": "incremental", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options,
        )

    def restart_vm_with_inc(self):
        images = self.params["images"]
        self.params["images"] = " ".join([images.split()[0]] + self.inc_backup_tags)
        self.prepare_main_vm()
        self.clone_vm = self.main_vm
        self.params["images"] = images

    def hotplug_inc_backup_disks(self):
        for idx, tag in enumerate(self.src_img_tags):
            self.params["image_backup_chain_%s" % tag] = self.inc_backup_tags[idx]
        self.add_target_data_disks()

    def disable_bitmaps(self):
        for idx, bitmap in enumerate(self.bitmaps):
            # disable function has already checked if the bitmap was disabled
            block_dirty_bitmap.block_dirty_bitmap_disable(
                self.main_vm, self.source_images[idx], bitmap
            )

            # record the count of the bitmap
            info = block_dirty_bitmap.get_bitmap_by_name(
                self.main_vm, self.source_images[idx], bitmap
            )
            self.bitmap_counts[info["name"]] = info["count"]

    def get_bitmaps_info(self):
        out = []
        for idx, bitmap in enumerate(self.bitmaps):
            info = block_dirty_bitmap.get_bitmap_by_name(
                self.main_vm, self.source_images[idx], bitmap
            )
            out.append(info)
        return out

    def check_bitmaps(self):
        for info in self.get_bitmaps_info():
            if info is None:
                self.test.fail("Failed to get bitmaps after migration")
            if info["recording"] is not False:
                self.test.fail("Bitmap was not disabled after migration")
            if info["count"] != self.bitmap_counts[info["name"]]:
                self.test.fail("Count of bitmap was changed after migration")

    def migrate_vm(self):
        mig_timeout = float(self.params["mig_timeout"])
        mig_protocol = self.params["migration_protocol"]
        capabilities = ast.literal_eval(self.params["migrate_capabilities"])
        self.main_vm.migrate(
            mig_timeout, mig_protocol, migrate_capabilities=capabilities, env=self.env
        )

    def rebase_inc_onto_base(self):
        return utils_misc.parallel(self.rebase_funcs)

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.disable_bitmaps()
        self.migrate_vm()
        self.check_bitmaps()
        self.hotplug_inc_backup_disks()
        self.do_incremental_backup()
        self.main_vm.destroy()
        self.rebase_inc_onto_base()
        self.restart_vm_with_inc()
        self.verify_data_files()


def run(test, params, env):
    """
    Do incremental live backup with bitmap after migrated on shared storage
    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for full backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. create another file
        6. disable bitmaps
        7. Migrate VM from src to dst, wait till it is finished
        8. add inc backup disks and do inc bakcup(sync: incremental) on dst
        9. shutdown VM on dst
       10. rebase inc images(inc-backup) onto base images(full-backup)
       11. start VM with inc images on dst, check files' md5
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkWithMigration(test, params, env)
    inc_test.run_test()
