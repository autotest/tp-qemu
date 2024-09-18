from virttest import utils_numeric

from provider import backup_utils, block_dirty_bitmap, blockdev_base


class BlockdevIncBackupResizeTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncBackupResizeTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        self.src_img_sizes = []
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.bitmaps.append("bitmap_%s" % tag)

        # Extend or shrink image size based on its original size
        self.src_img_sizes.append(
            int(
                float(
                    utils_numeric.normalize_data_size(
                        image_params["image_size"], order_magnitude="B"
                    )
                )
            )
        )

    def do_full_backup(self):
        extra_options = {
            "sync": "full",
            "persistent": True,
            "auto_disable_bitmap": False,
        }
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.bitmaps,
            **extra_options,
        )

    def prepare_data_disk(self, tag):
        """
        Override this function, only make fs and mount it
        :param tag: image tag
        """
        self.format_data_disk(tag)

    def gen_inc_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def check_bitmaps(self, node_name, bitmap_name):
        bitmap = block_dirty_bitmap.get_bitmap_by_name(
            self.main_vm, node_name, bitmap_name
        )
        # check if bitmap exists
        if bitmap is None:
            self.test.fail("Failed to get bitmap")

        # check if bitmap is persistent
        if not bitmap["persistent"]:
            self.test.fail("Bitmap should be persistent")

    def check_image_bitmaps_existed(self):
        # make sure persistent bitmaps always exist after VM shutdown
        for tag in self.params.objects("source_images"):
            disk = self.source_disk_define_by_params(self.params, tag)
            out = disk.info()

            if out:
                if self.params["check_bitmaps"] not in out:
                    self.test.fail("Persistent bitmaps should be in image")
            else:
                self.test.error("Error when querying image info with qemu-img")

    def check_image_size(self, node_name, block_size):
        for d in self.main_vm.monitor.cmd("query-block"):
            if d["inserted"]["node-name"] == node_name:
                node = d["inserted"]["image"]
                break
        else:
            self.test.error("Error when querying %s with query-block" % node_name)

        if int(node["virtual-size"]) != block_size:
            self.test.fail("image size %s != %s after block_resize")

    def block_resize_data_disks(self):
        for ratio in self.params.objects("disk_change_ratio"):
            for idx, tag in enumerate(self.src_img_tags):
                self.params.object_params(tag)
                block_size = int(self.src_img_sizes[idx] * float(ratio))
                args = (None, block_size, self.source_images[idx])
                self.main_vm.monitor.block_resize(*args)
                self.check_image_size(self.source_images[idx], block_size)
                self.check_bitmaps(self.source_images[idx], self.bitmaps[idx])

    def do_test(self):
        self.do_full_backup()
        self.gen_inc_files()
        self.main_vm.destroy()
        self.prepare_main_vm()
        self.block_resize_data_disks()
        self.main_vm.destroy()
        self.check_image_bitmaps_existed()


def run(test, params, env):
    """
    block_resize a qcow2 image with persistent bitmap stored on it

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add persistent bitmap
        5. create another file
        6. keep count of bitmaps, shutdown VM to store dirty maps
        7. start VM, record the count of bitmaps
        8. extend/shrink image size, the count should be the same
        9. shutdown VM to check persistent bitmaps always exist in image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupResizeTest(test, params, env)
    inc_test.run_test()
