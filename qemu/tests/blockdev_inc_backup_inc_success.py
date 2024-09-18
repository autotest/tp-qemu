from virttest import utils_misc

from provider import backup_utils, block_dirty_bitmap, blockdev_base


class BlockdevIncbkIncSyncSuccBitmapTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncbkIncSyncSuccBitmapTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.inc_backup_tags = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        self.inc_sync_mode = params["inc_sync_mode"]
        self.inc_bitmap_mode = params["inc_bitmap_mode"]
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.inc_backups.append("drive_%s" % image_chain[1])
        self.inc_backup_tags.append(image_chain[1])
        self.bitmaps.append("bitmap_%s" % tag)

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
        extra_options = {
            "sync": self.inc_sync_mode,
            "bitmap-mode": self.inc_bitmap_mode,
            "auto_disable_bitmap": False,
        }
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options,
        )

    def get_bitmaps_info(self):
        out = []
        for idx, bitmap in enumerate(self.bitmaps):
            node = self.source_images[idx]
            info = block_dirty_bitmap.get_bitmap_by_name(self.main_vm, node, bitmap)
            out.append(info)
        return out

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()
        self.check_bitmaps()
        self.clone_main_vm()
        self.check_images()

    def check_bitmaps(self):
        def _check_bitmaps():
            bitmaps = self.get_bitmaps_info()
            if not bitmaps:
                return False

            for info in bitmaps:
                if info["count"] != 0:
                    return False
            else:
                return True

        refresh_timeout = self.params.get_numeric("refresh_timeout", 10)
        if not utils_misc.wait_for(lambda: _check_bitmaps(), refresh_timeout, 0, 1):
            self.test.fail("count of bitmap should be 0 " "after incremental backup")

    def check_images(self):
        self.verify_data_files()

    def clone_main_vm(self):
        self.main_vm.destroy()
        imgs = [self.params["images"].split()[0]] + self.inc_backup_tags
        self.params["images"] = " ".join(imgs)
        self.prepare_main_vm()
        self.clone_vm = self.main_vm


def run(test, params, env):
    """
    Blockdev incremental backup test

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. create another file
        6. do inc bakcup(sync: incremental, bitmap-mode: on-success)
        7. check bitmap, count should be 0
        8. shutdown VM
        9. start VM with inc image, check md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkIncSyncSuccBitmapTest(test, params, env)
    inc_test.run_test()
