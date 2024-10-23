"""
Module for providing interfaces for exporting local image with
qemu-nbd and qemu internal nbd server.

Available classes:
- QemuNBDExportImage: Export local image with qemu-nbd
- InternalNBDExportImage: Export image with vm qemu internal nbd server

Available methods:
- create_image: Create a local image with qemu-img or
                with user defined command
- export_image: Export the local image
- stop_export: Stop exporting image
- suspend_export: Suspend exporting image
- list_exported_image: List nbd image with qemu-nbd
- hotplug_tls: Hotplug tls creds object for internal nbd server
- hotplug_image: Hotplug local image to be exported
- get_export_name: Get export name for internal nbd export
- start_nbd_server: Start internal nbd server
- add_nbd_image: Add image export to internal nbd server
- remove_nbd_image: Remove image export from internal nbd server
- stop_nbd_server: Stop internal nbd server
- wait_till_export_removed: Wait till BLOCK_EXPORT_DELETED is received,
                            this event will be emitted when a block export
                            is removed and its id can be reused.
- query_nbd_export: Get the nbd export information, please refer to
                    BlockExportInfo for details (since 5.2)

Use new block-export-add/block-export-del qmp commands to
create/delete block exports (since 5.2):
- The following params may be defined for block export
  block_export_uid: The uniqu block export id
  block_export_iothread: The name of the iothread object
  block_export_writable: 'yes' or 'no', 'yes' if clients should be able
                         to write to the export
  block_export_writethrough: 'yes' or 'no', 'yes' if caches flushed after
                             every write to the export
  block_export_fixed_iothread: 'yes' or 'no', 'yes' if the block node is
                               prevented from being moved to another thread
                               while the export is active
  block_export_remove_mode: 'safe' or 'hard'
  block_export_del_timeout: timeout when waiting for BLOCK_EXPORT_DELETED
- The following params may be defined for nbd export
  nbd_export_name: The export name
  nbd_export_description: Free-form description of the export(up to 4096b)
  nbd_export_bitmaps: bitmap names seperated by space, e.g. 'b1 b2 b3'
  nbd_allocation_exported: 'yes' or 'no', 'yes' if the allocation depth map
                           will be exported
"""

import logging
import os
import signal

from avocado.core import exceptions
from avocado.utils import process
from virttest import data_dir, nbd, qemu_devices, qemu_storage, utils_misc
from virttest.qemu_monitor import MonitorNotSupportedCmdError

from provider.job_utils import get_event_by_condition

LOG_JOB = logging.getLogger("avocado.test")


class NBDExportImage(object):
    """NBD local image export base class"""

    def __init__(self, params, local_image):
        """
        Initialize object.
        :param local_image: local image tag
        :param params: dictionary containing all test parameters.
        """
        self._tag = local_image
        self._params = params
        self._image_params = self._params.object_params(self._tag)

    def create_image(self):
        result = None
        if self._image_params.get("create_image_cmd"):
            result = process.run(
                self._image_params["create_image_cmd"], ignore_status=True, shell=True
            )
        elif not self._image_params.get_boolean("force_create_image"):
            _, result = qemu_storage.QemuImg(
                self._image_params, data_dir.get_data_dir(), self._tag
            ).create(self._image_params)

        if result and result.exit_status != 0:
            raise exceptions.TestFail(
                "Failed to create image, error: %s" % result.stderr.decode()
            )

    def export_image(self):
        raise NotImplementedError()

    def stop_export(self):
        raise NotImplementedError()


class QemuNBDExportImage(NBDExportImage):
    """Export local image with qemu-nbd command"""

    def __init__(self, params, local_image):
        super(QemuNBDExportImage, self).__init__(params, local_image)
        self._qemu_nbd = utils_misc.get_qemu_nbd_binary(self._params)
        filename_repr = (
            "json"
            if self._image_params.get("nbd_export_format") == "luks"
            else "filename"
        )
        self._local_filename = qemu_storage.get_image_repr(
            self._tag, self._image_params, data_dir.get_data_dir(), filename_repr
        )
        self._nbd_server_pid = None

    def export_image(self):
        LOG_JOB.info("Export image with qemu-nbd")
        self._nbd_server_pid = nbd.export_image(
            self._qemu_nbd, self._local_filename, self._tag, self._image_params
        )
        if self._nbd_server_pid is None:
            raise exceptions.TestFail("Failed to export image")

    def list_exported_image(self, nbd_image, nbd_image_params):
        LOG_JOB.info("List the nbd image with qemu-nbd")
        result = nbd.list_exported_image(self._qemu_nbd, nbd_image, nbd_image_params)
        if result.exit_status != 0:
            raise exceptions.TestFail(
                "Failed to list nbd image: %s" % result.stderr.decode()
            )

    def stop_export(self):
        if self._nbd_server_pid is not None:
            try:
                # when qemu-nbd crashes unexpectedly, we can handle it
                os.kill(self._nbd_server_pid, signal.SIGKILL)
            except Exception as e:
                LOG_JOB.warning("Error occurred when killing nbd server: %s", str(e))
            finally:
                self._nbd_server_pid = None

    def suspend_export(self):
        if self._nbd_server_pid is not None:
            LOG_JOB.info("Suspend qemu-nbd by sending SIGSTOP")
            try:
                os.kill(self._nbd_server_pid, signal.SIGSTOP)
            except Exception as e:
                LOG_JOB.warning(
                    "Error occurred when suspending" "nbd server: %s", str(e)
                )

    def resume_export(self):
        if self._nbd_server_pid is not None:
            LOG_JOB.info("Resume qemu-nbd by sending SIGCONT")
            try:
                os.kill(self._nbd_server_pid, signal.SIGCONT)
            except Exception as e:
                LOG_JOB.warning("Error occurred when resuming nbd server: %s", str(e))


class InternalNBDExportImage(NBDExportImage):
    """Export image with qemu internal nbd server"""

    def __init__(self, vm, params, local_image):
        super(InternalNBDExportImage, self).__init__(params, local_image)
        self._tls_creds_id = None
        self._node_name = None
        self._image_devices = None
        self._vm = vm
        self._export_uid = None

    def get_export_name(self):
        """export name is the node name if nbd_export_name is not set"""
        return (
            self._image_params["nbd_export_name"]
            if self._image_params.get("nbd_export_name")
            else self._node_name
        )

    def hotplug_image(self):
        """Hotplug the image to be exported"""
        devices = self._vm.devices.images_define_by_params(
            self._tag, self._image_params, "disk"
        )

        # Only hotplug protocol and format node and the related objects
        devices.pop()
        self._node_name = devices[-1].get_qid()
        self._image_devices = devices

        LOG_JOB.info("Plug devices(without image device driver)")
        for dev in devices:
            ret = self._vm.devices.simple_hotplug(dev, self._vm.monitor)
            if not ret[1]:
                raise exceptions.TestFail(
                    "Failed to hotplug device '%s': %s." % (dev, ret[0])
                )

    def hotplug_tls(self):
        """Hotplug tls creds object for nbd server"""
        if self._image_params.get("nbd_unix_socket"):
            LOG_JOB.info("TLS is only supported with IP")
        elif self._image_params.get("nbd_server_tls_creds"):
            LOG_JOB.info("Plug server tls creds device")
            self._tls_creds_id = "%s_server_tls_creds" % self._tag
            dev = qemu_devices.qdevices.QObject("tls-creds-x509")
            dev.set_param("id", self._tls_creds_id)
            dev.set_param("endpoint", "server")
            dev.set_param("dir", self._image_params["nbd_server_tls_creds"])
            ret = self._vm.devices.simple_hotplug(dev, self._vm.monitor)
            if not ret[1]:
                raise exceptions.TestFail(
                    "Failed to hotplug device '%s': %s." % (dev, ret[0])
                )

    def start_nbd_server(self):
        """Start internal nbd server"""
        server = (
            {"type": "unix", "path": self._image_params["nbd_unix_socket"]}
            if self._image_params.get("nbd_unix_socket")
            else {
                "type": "inet",
                "host": "0.0.0.0",
                "port": self._image_params.get("nbd_port", "10809"),
            }
        )

        LOG_JOB.info("Start internal nbd server")
        return self._vm.monitor.nbd_server_start(server, self._tls_creds_id)

    def _block_export_add(self):
        # block export arguments
        self._export_uid = self._image_params.get(
            "block_export_uid", "block_export_%s" % self._node_name
        )
        iothread = self._image_params.get("block_export_iothread")
        writethrough = (
            self._image_params["block_export_writethrough"] == "yes"
            if self._image_params.get("block_export_writethrough")
            else None
        )
        fixed = (
            self._image_params["block_export_fixed_iothread"] == "yes"
            if self._image_params.get("block_export_fixed_iothread")
            else None
        )

        # to be compatible with the original test cases using nbd-server-add
        export_writable = self._image_params.get(
            "block_export_writable", self._image_params.get("nbd_export_writable")
        )
        writable = export_writable == "yes" if export_writable else None

        # nbd specified arguments
        kw = {
            "name": self._image_params.get("nbd_export_name"),
            "description": self._image_params.get("nbd_export_description"),
        }
        if self._image_params.get("nbd_export_bitmaps") is not None:
            kw["bitmaps"] = self._image_params.objects("nbd_export_bitmaps")
        if self._image_params.get("nbd_allocation_exported") is not None:
            kw["allocation-depth"] = (
                self._image_params["nbd_allocation_exported"] == "yes"
            )

        return self._vm.monitor.block_export_add(
            self._export_uid,
            "nbd",
            self._node_name,
            iothread,
            fixed,
            writable,
            writethrough,
            **kw,
        )

    def _block_export_del(self):
        return self._vm.monitor.block_export_del(
            self._export_uid, self._image_params.get("block_export_remove_mode")
        )

    def wait_till_export_removed(self):
        """
        When we remove an export with block-export-del, the export may still
        stay around after this command returns, BLOCK_EXPORT_DELETED will be
        emitted when a block export is removed and its id can be reused.
        """
        if self._export_uid is not None:
            cond = {"id": self._export_uid}
            tmo = self._image_params.get_numeric("block_export_del_timeout", 60)
            event = get_event_by_condition(
                self._vm, "BLOCK_EXPORT_DELETED", tmo, **cond
            )
            if event is None:
                raise exceptions.TestFail("Failed to receive BLOCK_EXPORT_DELETED")
            self._export_uid = None

    def add_nbd_image(self, node_name=None):
        """
        Add an image(to be exported) to internal nbd server.
        :param node_name: block node name, the node might be hotplugged
                          by other utils, or the node has already been
                          present in VM.
        """
        if node_name:
            self._node_name = node_name

        LOG_JOB.info("Add image node to nbd server")
        try:
            return self._block_export_add()
        except MonitorNotSupportedCmdError:
            self._export_uid = None
            return self._vm.monitor.nbd_server_add(
                self._node_name,
                self._image_params.get("nbd_export_name"),
                self._image_params.get("nbd_export_writable"),
                self._image_params.get("nbd_export_bitmaps"),
            )

    def remove_nbd_image(self):
        """Remove the exported image from internal nbd server"""
        LOG_JOB.info("Remove image from nbd server")
        try:
            return self._block_export_del()
        except MonitorNotSupportedCmdError:
            return self._vm.monitor.nbd_server_remove(
                self.get_export_name(), self._image_params.get("nbd_remove_mode")
            )

    def stop_nbd_server(self):
        """Stop internal nbd server, it also unregisters all devices"""
        LOG_JOB.info("Stop nbd server")
        return self._vm.monitor.nbd_server_stop()

    def export_image(self):
        """
        For internal nbd server, in order to export an image, start the
        internal nbd server first, then add a local image to server.
        """
        self.start_nbd_server()
        self.add_nbd_image()

    def stop_export(self):
        self.remove_nbd_image()
        self.wait_till_export_removed()
        self.stop_nbd_server()

    def query_nbd_export(self):
        """Get the nbd export info"""
        exports = self._vm.monitor.query_block_exports()
        nbd_exports = [e for e in exports if e["id"] == self._export_uid]
        return nbd_exports[0] if nbd_exports else None
