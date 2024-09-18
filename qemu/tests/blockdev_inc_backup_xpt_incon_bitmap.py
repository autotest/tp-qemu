import json
import logging

from avocado.utils import process
from virttest import data_dir, utils_misc

from provider import backup_utils
from provider.blockdev_base import BlockdevBaseTest

LOG_JOB = logging.getLogger("avocado.test")


class BlkdevIncXptInconBitmap(BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlkdevIncXptInconBitmap, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.bitmaps.append("bitmap_%s" % tag)
        image_params["nbd_export_bitmaps"] = "bitmap_%s" % tag

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

    def kill_vm_after_restart(self):
        LOG_JOB.info("Re-start vm again")
        self.main_vm.create()
        self.main_vm.wait_for_login()
        LOG_JOB.info("Kill vm after its start")
        self.main_vm.monitors = []
        self.main_vm.destroy(gracefully=False)

    def check_bitmap_status(self, inconsistent=False):
        def _get_bitmap_info(bitmap_name):
            src_img = self.source_disk_define_by_params(
                self.params, self.src_img_tags[0]
            )
            output = json.loads(src_img.info(output="json"))
            bitmaps = output["format-specific"]["data"].get("bitmaps")
            if bitmaps:
                for bitmap in bitmaps:
                    if bitmap["name"] == bitmap_name:
                        return bitmap
            return None

        if inconsistent:
            LOG_JOB.info("Check bitmap is inconsistent stored in image")
        else:
            LOG_JOB.info("Check persistent bitmap stored in image")
        bitmap_info = _get_bitmap_info(self.bitmaps[0])
        if not bitmap_info:
            self.test.fail("Persistent bitmap not stored in image")
        if inconsistent and "in-use" not in bitmap_info["flags"]:
            self.test.fail("Bitmap stored is not inconsistent")

    def expose_inconsistent_bitmap(self):
        LOG_JOB.info("Export inconsistent bitmap with qemu-nbd")
        img_path = data_dir.get_data_dir()
        qemu_nbd_cmd = utils_misc.get_qemu_nbd_binary(self.params)
        cmd = self.params.get("export_cmd") % (qemu_nbd_cmd, self.bitmaps[0], img_path)
        result = process.run(
            cmd, ignore_status=True, shell=True, ignore_bg_processes=True
        )
        if result.exit_status == 0:
            ck_qemunbd_pid = self.params.get("ck_qemunbd_pid")
            qemu_nbd_ck = process.run(
                ck_qemunbd_pid, ignore_status=True, shell=True, ignore_bg_processes=True
            )
            qemu_nbd_pid = qemu_nbd_ck.stdout_text.strip()
            utils_misc.kill_process_tree(qemu_nbd_pid, 9, timeout=60)
            self.test.fail("Can expose image with a non-exist bitmap")

        error_msg = self.params.get("error_msg") % self.bitmaps[0]
        if error_msg not in result.stderr.decode():
            self.test.fail(result.stderr.decode())

    def do_test(self):
        self.do_full_backup()
        self.gen_inc_files()
        self.main_vm.destroy(free_mac_addresses=False)
        self.check_bitmap_status()
        self.kill_vm_after_restart()
        self.check_bitmap_status(inconsistent=True)
        self.expose_inconsistent_bitmap()


def run(test, params, env):
    """
    Expose inconsistent bitmap via qemu-nbd

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add persistent bitmap
        5. create another file
        6. shutdown VM via kill cmd
        7. expose inconsistent bitmap with qemu-nbd

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    expose_incon_bitmap = BlkdevIncXptInconBitmap(test, params, env)
    expose_incon_bitmap.run_test()
