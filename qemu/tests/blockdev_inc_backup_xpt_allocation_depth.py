import json
import socket

from avocado.utils import process
from virttest.qemu_storage import filename_to_file_opts
from virttest.utils_misc import get_qemu_img_binary

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.nbd_image_export import InternalNBDExportImage, QemuNBDExportImage


class BlockdevIncbkXptAllocDepth(BlockdevLiveBackupBaseTest):
    """Allocation depth export test"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkXptAllocDepth, self).__init__(test, params, env)
        self._base_image, self._snapshot_image = self.params.objects(
            "image_backup_chain"
        )
        localhost = socket.gethostname()
        self.params["nbd_server"] = localhost if localhost else "localhost"
        self._nbd_image_obj = self.source_disk_define_by_params(
            self.params, self.params["nbd_image_tag"]
        )
        self._block_export_uid = self.params.get("block_export_uid")
        self._nbd_export = None
        self._is_exported = False

    def _init_nbd_export(self, tag):
        self._nbd_export = (
            InternalNBDExportImage(self.main_vm, self.params, tag)
            if self._block_export_uid
            else QemuNBDExportImage(self.params, tag)
        )

    def _start_nbd_export(self, tag):
        if self._block_export_uid is not None:
            # export local image with block-export-add
            self._nbd_export.start_nbd_server()
            self._nbd_export.add_nbd_image("drive_%s" % tag)
        else:
            # export local image with qemu-nbd
            # we should stop vm and rebase sn onto base
            if self.main_vm.is_alive():
                self.main_vm.destroy()
                self._rebase_sn_onto_base()
            self._nbd_export.export_image()
        self._is_exported = True

    def _rebase_sn_onto_base(self):
        disk = self.source_disk_define_by_params(self.params, self._snapshot_image)
        disk.rebase(params=self.params)

    def post_test(self):
        self.stop_export()
        super(BlockdevIncbkXptAllocDepth, self).post_test()

    def stop_export(self):
        """stop nbd export"""
        if self._is_exported:
            self._nbd_export.stop_export()
            self._is_exported = False

    def export_image(self, tag):
        """export image from nbd server"""
        self._init_nbd_export(tag)
        self._start_nbd_export(tag)

    def check_allocation_depth_from_export(self, zero, data):
        """
        check allocation depth from output of qemu-img map
            local(base image): zero: false, data: false
            backing(snapshot): zero: true, data: true
        """
        opts = filename_to_file_opts(self._nbd_image_obj.image_filename)
        opts[self.params["dirty_bitmap_opt"]] = "qemu:allocation-depth"
        map_cmd = "{qemu_img} map --output=json {args}".format(
            qemu_img=get_qemu_img_binary(self.params),
            args="'json:%s'" % json.dumps(opts),
        )

        result = process.run(map_cmd, ignore_status=False, shell=True)
        for item in json.loads(result.stdout.decode().strip()):
            if item["zero"] is zero and item["data"] is data:
                break
        else:
            self.test.fail('Failed to get "zero": %s, "data": %s' % (zero, data))

    def do_test(self):
        self.do_full_backup()
        self.export_image(self._base_image)
        self.check_allocation_depth_from_export(zero=False, data=False)
        self.stop_export()
        self.export_image(self._snapshot_image)
        self.check_allocation_depth_from_export(zero=True, data=True)


def run(test, params, env):
    """
    Allocation depth export test.

    test steps:
        1. boot VM with a data image
        2. create fs on the data image and create a file
        3. hotplug a 'base' image, then hotplug a 'sn' image(base->sn)
        4. do full backup (from data image to base image)
        5. export 'base' with allocation depth
        6. check allocation depth info (local: zero: false, data: false)
        7. export 'sn' with allocation depth
        8. check allocation depth info (backing: zero: true, data: true)

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkXptAllocDepth(test, params, env)
    inc_test.run_test()
