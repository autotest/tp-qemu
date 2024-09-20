from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils, blockdev_base


class BlkdevIncNA(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlkdevIncNA, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
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
            "bitmap": self.bitmaps[0],
            "bitmap-mode": self.inc_bitmap_mode,
            "auto_disable_bitmap": False,
        }
        inc_backup = backup_utils.blockdev_backup_qmp_cmd
        cmd, arguments = inc_backup(
            self.source_images[0], self.inc_backups[0], **extra_options
        )
        try:
            self.main_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            qmp_error_msg = self.params.get("qmp_error_msg")
            if qmp_error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail(
                "Inc backup with invalid bitmap mode:%s" % self.inc_bitmap_mode
            )

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()


def run(test, params, env):
    """
    Incremental backup with sync:incremental & bitmap mode:never/always

    test steps:
        1). boot VM with a 2G data disk
        2). format data disk and mount it, create a file
        3). add target disks for backup to VM via qmp commands
        4). do full backup and add non-persistent bitmap
        5). create another file
        6). do inc bakcup(sync: incremental and bitmap-mode:never/always)

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_no_bpmode = BlkdevIncNA(test, params, env)
    inc_no_bpmode.run_test()
