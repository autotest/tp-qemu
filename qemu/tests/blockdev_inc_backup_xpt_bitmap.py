import json
import socket

from avocado.utils import process
from virttest import qemu_storage, utils_misc

from provider import backup_utils
from provider.blockdev_base import BlockdevBaseTest
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevIncBackupXptBitmapTest(BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncBackupXptBitmapTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.bitmaps = []
        self.nbd_exports = []
        self.nbd_images = []
        self.src_img_tags = params.objects("source_images")
        localhost = socket.gethostname()
        self.params["nbd_server"] = localhost if localhost else "localhost"
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.bitmaps.append("bitmap_%s" % tag)
        image_params["nbd_export_bitmaps"] = "bitmap_%s" % tag
        self.nbd_exports.append(QemuNBDExportImage(image_params, tag))
        self.nbd_images.append(
            qemu_storage.QemuImg(
                self.params.object_params(image_params["nbd_image_tag"]),
                None,
                image_params["nbd_image_tag"],
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
            list(self.bitmaps),
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

    def expose_persistent_bitmaps(self):
        for xpt in self.nbd_exports:
            xpt.export_image()

    def check_info_from_export_bitmaps(self):
        qemu_img = utils_misc.get_qemu_img_binary(self.params)

        for i, nbd_img in enumerate(self.nbd_images):
            opts = qemu_storage.filename_to_file_opts(nbd_img.image_filename)
            opts[self.params["dirty_bitmap_opt"]] = (
                "qemu:dirty-bitmap:%s" % self.bitmaps[i]
            )
            args = "'json:%s'" % json.dumps(opts)

            map_cmd = "{qemu_img} map --output=human {args}".format(
                qemu_img=qemu_img, args=args
            )
            result = process.run(map_cmd, ignore_status=True, shell=True)
            if result.exit_status != 0:
                self.test.fail("Failed to run map command: %s" % result.stderr.decode())
            if nbd_img.image_filename not in result.stdout_text:
                self.test.fail("Failed to get bitmap info.")

    def clean_images(self):
        for obj in self.nbd_exports:
            obj.stop_export()
        super(BlockdevIncBackupXptBitmapTest, self).clean_images()

    def do_test(self):
        self.do_full_backup()
        self.gen_inc_files()
        self.main_vm.destroy()
        self.expose_persistent_bitmaps()
        self.check_info_from_export_bitmaps()


def run(test, params, env):
    """
    Expose persistent bitmaps via qemu-nbd

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add persistent bitmap
        5. create another file
        6. shutdown VM
        7. expose persistent bitmaps with qemu-nbd
        8. qemu-img map can show incremental info from bitmaps

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupXptBitmapTest(test, params, env)
    inc_test.run_test()
