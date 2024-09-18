from provider import backup_utils, block_dirty_bitmap, blockdev_base


class BlockdevIncreamentalBackupBitmapTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncreamentalBackupBitmapTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        self.sync_mode = params.get("sync_mode", "bitmap")
        self.bitmap_mode = params.get("bitmap_mode", "always")
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.inc_backups.append("drive_%s" % image_chain[1])
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
        extra_options = {"sync": self.sync_mode, "auto_disable_bitmap": False}
        if self.sync_mode != "top":
            extra_options["bitmap-mode"] = self.bitmap_mode
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options,
        )

    def create_snapshot(self, source):
        snapshot_options = {}
        source_node = "drive_%s" % source
        source_params = self.params.object_params(source)
        snapshot_tag = source_params["snapshot"]
        snapshot_node = "drive_%s" % snapshot_tag
        snapshot_img = self.target_disk_define_by_params(self.params, snapshot_tag)
        snapshot_img.hotplug(self.main_vm)
        self.trash.append(snapshot_img)
        backup_utils.blockdev_snapshot(
            self.main_vm, source_node, snapshot_node, **snapshot_options
        )

    def create_snapshots(self):
        return list(map(self.create_snapshot, self.src_img_tags))

    def get_bitmaps_info(self):
        out = []
        for idx, bitmap in enumerate(self.bitmaps):
            node = self.source_images[idx]
            info = block_dirty_bitmap.get_bitmap_by_name(self.main_vm, node, bitmap)
            out.append(info)
        return out

    def do_test(self):
        self.do_full_backup()
        if self.sync_mode == "top":
            self.create_snapshots()
        self.generate_inc_files()
        self.main_vm.pause()
        self.do_incremental_backup()
        if self.sync_mode != "top":
            self.check_bitmaps()
        self.compare_images()

    def check_bitmaps(self):
        for info in self.get_bitmaps_info():
            if self.bitmap_mode == "never":
                keyword = "is"
                condiction = info["count"] > 0
            else:
                keyword = "is not"
                condiction = info["count"] == 0
            assert condiction, "bitmap '%s' %s clear in '%s' mode: \n%s" % (
                info["name"],
                keyword,
                self.bitmap_mode,
                info,
            )

    def compare_images(self):
        self.main_vm.destroy()
        return list(map(self._compare_image, self.src_img_tags))

    def _compare_image(self, src_tag):
        src_params = self.params.object_params(src_tag)
        overlay_tag = src_params.objects("image_backup_chain")[-1]
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
