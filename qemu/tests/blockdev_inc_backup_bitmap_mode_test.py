import logging

from provider import backup_utils
from provider import blockdev_base
from provider import block_dirty_bitmap


class BlockdevIncreamentalBackupBitmapTest(blockdev_base.BlockdevBaseTest):

    def __init__(self, test, params, env):
        super(
            BlockdevIncreamentalBackupBitmapTest,
            self).__init__(
            test,
            params,
            env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.bitmaps = []
        for tag in params.objects('source_images'):
            image_params = params.object_params(tag)
            image_chain = image_params.objects("image_chain")
            self.source_images.append("drive_%s" % tag)
            self.full_backups.append("drive_%s" % image_chain[0])
            self.inc_backups.append("drive_%s" % image_chain[1])
            self.bitmaps.append("bitmap_%s" % tag)
            inc_img_tag = image_chain[-1]
            inc_img_params = params.object_params(inc_img_tag)
            inc_img_params['image_chain'] = image_params['image_chain']

    def do_full_backup(self):
        extra_options = {"sync": "full", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.bitmaps,
            **extra_options)

    def generate_inc_files(self):
        for tag in self.params.objects("source_images"):
            self.generate_data_file(tag)

    def do_incremental_backup(self):
        sync_mode = self.params.get("sync_mode", "bitmap")
        bitmap_mode = self.params.get("bitmap_mode", "always")
        extra_options = {'sync': sync_mode,
                         'bitmap-mode': bitmap_mode,
                         'auto_disable_bitmap': False}
        logging.info("bitmap sync mode: %s" % bitmap_mode)
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options)

    def get_bitmaps_info(self):
        out = []
        for idx, bitmap in enumerate(self.bitmaps):
            node = self.source_images[idx]
            info = block_dirty_bitmap.get_bitmap_by_name(
                self.main_vm, node, bitmap)
            out.append(info)
        return out

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.main_vm.pause()
        self.do_incremental_backup()
        self.check_bitmaps()
        self.compare_image()

    def check_bitmaps(self):
        bitmap_mode = self.params.get("bitmap_mode", "always")
        for info in self.get_bitmaps_info():
            if bitmap_mode == "never":
                keyword = "is"
                condiction = info["count"] > 0
            else:
                keyword = "is not"
                condiction = info["count"] == 0
            assert condiction, "bitmap '%s' %s clear in '%s' mode: \n%s" % (
                info["name"], keyword, bitmap_mode, info)

    def compare_image(self):
        self.main_vm.destroy()
        for src_tag in self.params.objects("source_images"):
            src_params = self.params.object_params(src_tag)
            overlay_tag = src_params.objects("image_chain")[-1]
            src_img = self.disk_define_by_params(self.params, src_tag)
            dst_img = self.disk_define_by_params(self.params, overlay_tag)
            result = src_img.compare_to(dst_img)
            assert result.exit_status == 0, result.stdout


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
        7. do incremental backup with bitmap-mode option
        8. check bitmap count
        9. compare overlay image and source image(optional)

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncreamentalBackupBitmapTest(test, params, env)
    inc_test.run_test()
