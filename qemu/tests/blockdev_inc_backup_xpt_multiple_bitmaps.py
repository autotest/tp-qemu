import json
import socket

from avocado.utils import process
from virttest.qemu_storage import filename_to_file_opts
from virttest.utils_misc import get_qemu_img_binary

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.nbd_image_export import InternalNBDExportImage, QemuNBDExportImage


class BlockdevIncbkXptMutBitmaps(BlockdevLiveBackupBaseTest):
    """Multiple bitmaps export test"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkXptMutBitmaps, self).__init__(test, params, env)
        self._bitmaps = params.objects("bitmap_list")
        self._bitmap_states = [True, False]
        localhost = socket.gethostname()
        self.params["nbd_server"] = localhost if localhost else "localhost"
        self._nbd_image_obj = self.source_disk_define_by_params(
            self.params, self.params["nbd_image_tag"]
        )
        self._block_export_uid = self.params.get("block_export_uid")
        self._nbd_export = None
        self._is_exported = False

    def _init_nbd_export(self):
        self._nbd_export = (
            InternalNBDExportImage(self.main_vm, self.params, self._full_bk_images[0])
            if self._block_export_uid
            else QemuNBDExportImage(self.params, self._full_bk_images[0])
        )

    def check_nbd_export_info(self):
        if self._block_export_uid is not None:
            info = self._nbd_export.query_nbd_export()
            if info is None:
                self.test.fail("Failed to get the nbd block export")

            if (
                not info
                or info["shutting-down"]
                or info["id"] != self._block_export_uid
                or info["type"] != "nbd"
                or info["node-name"] != self._full_bk_nodes[0]
            ):
                self.test.fail(
                    "Failed to get the correct export information: %s" % info
                )

    def do_nbd_export(self):
        if self._block_export_uid is not None:
            self._nbd_export.start_nbd_server()
            self._nbd_export.add_nbd_image(self._full_bk_nodes[0])
        else:
            self.main_vm.destroy()
            self._nbd_export.export_image()
        self._is_exported = True

    def prepare_test(self):
        self.prepare_main_vm()
        self.add_target_data_disks()
        self._init_nbd_export()

    def post_test(self):
        if self._is_exported:
            self._nbd_export.stop_export()
        super(BlockdevIncbkXptMutBitmaps, self).post_test()

    def add_persistent_bitmaps(self):
        """Add two bitmaps, one is enabled while the other is disabled"""
        bitmaps = [
            {
                "node": self._full_bk_nodes[0],
                "name": b,
                "persistent": True,
                "disabled": s,
            }
            for b, s in zip(self._bitmaps, self._bitmap_states)
        ]
        job_list = [
            {"type": "block-dirty-bitmap-add", "data": data} for data in bitmaps
        ]
        self.main_vm.monitor.transaction(job_list)

    def check_bitmaps_from_export(self):
        qemu_img = get_qemu_img_binary(self.params)

        opts = filename_to_file_opts(self._nbd_image_obj.image_filename)
        for bm in self._bitmaps:
            opts[self.params["dirty_bitmap_opt"]] = "qemu:dirty-bitmap:%s" % bm
            args = "'json:%s'" % json.dumps(opts)
            map_cmd = "{qemu_img} map --output=human {args}".format(
                qemu_img=qemu_img, args=args
            )
            result = process.run(map_cmd, ignore_status=False, shell=True)
            if self._nbd_image_obj.image_filename not in result.stdout_text:
                self.test.fail("Failed to get bitmap info.")

    def do_test(self):
        self.add_persistent_bitmaps()
        self.do_nbd_export()
        self.check_nbd_export_info()
        self.check_bitmaps_from_export()


def run(test, params, env):
    """
    Multiple bitmaps export test

    test steps:
        1. boot VM
        2. hot-plug an image to be exported
        3. Add two bitmaps to the hot-plugged image
        4. export the hot-plugged image two bitmaps
        5. check bitmaps info with qemu:dirty-bitmap:bitmap_name

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkXptMutBitmaps(test, params, env)
    inc_test.run_test()
