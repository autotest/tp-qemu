from provider import backup_utils, block_dirty_bitmap, blockdev_base


class BlockdevIncBackupNonPersistentBitmapTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncBackupNonPersistentBitmapTest, self).__init__(
            test, params, env
        )
        self.source_images = []
        self.full_backups = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        self.bitmap_count = 0
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
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

    def get_bitmaps_info(self):
        out = []
        for idx, bitmap in enumerate(self.bitmaps):
            node = self.source_images[idx]
            info = block_dirty_bitmap.get_bitmap_by_name(self.main_vm, node, bitmap)
            out.append(info)
        return out

    def prepare_data_disk(self, tag):
        """
        Override this function, only make fs and mount it
        :param tag: image tag
        """
        self.format_data_disk(tag)

    def write_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def check_bitmaps(self, file_write=False):
        bitmaps = self.get_bitmaps_info()
        if not bitmaps:
            self.test.fail("No bitmap was found.")

        for info in bitmaps:
            # check if bitmap is non-persistent
            if info["persistent"]:
                self.test.fail("It should be non-persistent")

            # check if count is changed after file writing
            if file_write:
                if info["count"] <= self.bitmap_count:
                    self.test.fail(
                        "count of bitmap should be greater than "
                        "the original after writing a file"
                    )
            else:
                self.bitmap_count = info["count"]

    def check_image_info(self):
        # make sure non-persistent bitmaps never exist after VM shutdown
        for tag in self.params.objects("source_images"):
            params = self.params.object_params(tag)
            disk = self.source_disk_define_by_params(params, tag)
            out = disk.info()

            if out:
                if self.params["check_bitmaps"] in out:
                    self.test.fail("bitmap should not be in image")
            else:
                self.test.error("Error when querying image info by qemu-img")

    def do_test(self):
        self.do_full_backup()
        self.check_bitmaps(file_write=False)
        self.write_files()
        self.check_bitmaps(file_write=True)
        self.destroy_vms()
        self.check_image_info()


def run(test, params, env):
    """
    Blockdev incremental backup test: Add a non-persistent bitmap to image

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. check bitmap, persistent is False
        6. create another file
        7. check bitmap, count changed
        8. shutdown VM
        9. check non-persistent bitmaps never exist in image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupNonPersistentBitmapTest(test, params, env)
    inc_test.run_test()
