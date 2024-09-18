import socket

from virttest.qemu_devices.qdevices import QBlockdevFormatNode
from virttest.qemu_monitor import QMPCmdError

from provider.backup_utils import blockdev_batch_backup
from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.nbd_image_export import InternalNBDExportImage


class BlockdevIncbkExposeActiveBitmap(BlockdevLiveBackupBaseTest):
    """Expose an active bitmap"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkExposeActiveBitmap, self).__init__(test, params, env)

        if self.params.get_boolean("enable_nbd"):
            self.params["nbd_server_data1"] = self.params.get("nbd_server")
            self.params["nbd_client_tls_creds_data1"] = self.params.get(
                "nbd_client_tls_creds"
            )
        self._nbd_export = None
        localhost = socket.gethostname()
        self.params["nbd_server_full"] = localhost if localhost else "localhost"
        self.params["nbd_export_bitmaps_full"] = self._bitmaps[0]
        self._fleecing_image_obj = self.source_disk_define_by_params(
            self.params, self._full_bk_images[0]
        )
        self.trash.append(self._fleecing_image_obj)

    def add_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
            "persistent": "off",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def add_target_data_disks(self):
        self._fleecing_image_obj.create(self.params)
        tag = self._fleecing_image_obj.tag
        devices = self.main_vm.devices.images_define_by_params(
            tag, self.params.object_params(tag), "disk"
        )
        devices.pop()  # ignore the front end device

        for dev in devices:
            if isinstance(dev, QBlockdevFormatNode):
                dev.params["backing"] = self._source_nodes[0]
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s'" % dev)

    def prepare_test(self):
        self.prepare_main_vm()
        self.add_bitmap()
        self.prepare_data_disks()
        self.add_target_data_disks()
        self._nbd_export = InternalNBDExportImage(
            self.main_vm, self.params, self._full_bk_images[0]
        )
        self._nbd_export.start_nbd_server()

    def expose_active_bitmap(self):
        try:
            self._nbd_export.add_nbd_image(self._full_bk_nodes[0])
        except QMPCmdError as e:
            error_msg = self.params["error_msg"] % self._bitmaps[0]
            if error_msg not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("active bitmap export completed unexpectedly")

    def do_full_backup(self):
        blockdev_batch_backup(
            self.main_vm,
            self._source_nodes,
            self._full_bk_nodes,
            None,
            **self._full_backup_options,
        )

    def do_test(self):
        self.do_full_backup()
        self.expose_active_bitmap()


def run(test, params, env):
    """
    Expose an active bitmap

    test steps:
        1. boot VM with a data disk
        2. add a bitmap to the data disk and create a file
        3. hotplug a fleecing disk
        3. do backup(sync=none, data disk->fleecing disk)
        4. export the gleecing image from internal nbd server,
           it should fail with proper error message

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkExposeActiveBitmap(test, params, env)
    inc_test.run_test()
