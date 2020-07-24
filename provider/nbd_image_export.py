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
- list_exported_image: List nbd image with qemu-nbd
- hotplug_tls: Hotplug tls creds object for internal nbd server
- hotplug_image: Hotplug local image to be exported
- get_export_name: Get export name for internal nbd export
- start_nbd_server: Start internal nbd server
- add_nbd_image: Add image to internal nbd server
- remove_nbd_image: Remove image from internal nbd server
- stop_nbd_server: Stop internal nbd server
"""

import os
import signal
import logging

from avocado.utils import process
from avocado.core import exceptions

from virttest import nbd
from virttest import data_dir
from virttest import qemu_storage
from virttest import utils_misc
from virttest import qemu_devices


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
        if self._image_params.get('create_image_cmd'):
            result = process.run(self._image_params['create_image_cmd'],
                                 ignore_status=True, shell=True)
        elif not self._image_params.get_boolean("force_create_image"):
            _, result = qemu_storage.QemuImg(
                self._image_params,
                data_dir.get_data_dir(),
                self._tag
            ).create(self._image_params)

        if result.exit_status != 0:
            raise exceptions.TestFail('Failed to create image, error: %s'
                                      % result.stderr.decode())

    def export_image(self):
        raise NotImplementedError()

    def stop_export(self):
        raise NotImplementedError()


class QemuNBDExportImage(NBDExportImage):
    """Export local image with qemu-nbd command"""

    def __init__(self, params, local_image):
        super(QemuNBDExportImage, self).__init__(params, local_image)
        self._qemu_nbd = utils_misc.get_qemu_nbd_binary(self._params)
        filename_repr = 'json' if self._image_params.get(
            'nbd_export_format') == 'luks' else 'filename'
        self._local_filename = qemu_storage.get_image_repr(
            self._tag, self._image_params,
            data_dir.get_data_dir(), filename_repr)
        self._nbd_server_pid = None

    def export_image(self):
        logging.info("Export image with qemu-nbd")
        self._nbd_server_pid = nbd.export_image(self._qemu_nbd,
                                                self._local_filename,
                                                self._tag, self._image_params)
        if self._nbd_server_pid is None:
            raise exceptions.TestFail('Failed to export image')

    def list_exported_image(self, nbd_image, nbd_image_params):
        logging.info("List the nbd image with qemu-nbd")
        result = nbd.list_exported_image(self._qemu_nbd, nbd_image,
                                         nbd_image_params)
        if result.exit_status != 0:
            raise exceptions.TestFail('Failed to list nbd image: %s'
                                      % result.stderr.decode())

    def stop_export(self):
        if self._nbd_server_pid is not None:
            try:
                # when qemu-nbd crashes unexpectedly, we can handle it
                os.kill(self._nbd_server_pid, signal.SIGKILL)
            except Exception as e:
                logging.warn("Error occurred when killing nbd server: %s"
                             % str(e))
            finally:
                self._nbd_server_pid = None


class InternalNBDExportImage(NBDExportImage):
    """Export image with qemu internal nbd server"""

    def __init__(self, vm, params, local_image):
        super(InternalNBDExportImage, self).__init__(params, local_image)
        self._tls_creds_id = None
        self._node_name = None
        self._image_devices = None
        self._vm = vm

    def get_export_name(self):
        """export name is the node name if nbd_export_name is not set"""
        return self._image_params['nbd_export_name'] if self._image_params.get(
            'nbd_export_name') else self._node_name

    def hotplug_image(self):
        """Hotplug the image to be exported"""
        devices = self._vm.devices.images_define_by_params(self._tag,
                                                           self._image_params,
                                                           'disk')

        # Only hotplug protocol and format node and the related objects
        devices.pop()
        self._node_name = devices[-1].get_qid()
        self._image_devices = devices

        logging.info("Plug devices(without image device driver)")
        for dev in devices:
            ret = self._vm.devices.simple_hotplug(dev, self._vm.monitor)
            if not ret[1]:
                raise exceptions.TestFail("Failed to hotplug device '%s': %s."
                                          % (dev, ret[0]))

    def hotplug_tls(self):
        """Hotplug tls creds object for nbd server"""
        if self._image_params.get('nbd_unix_socket'):
            logging.info('TLS is only supported with IP')
        elif self._image_params.get('nbd_server_tls_creds'):
            logging.info("Plug server tls creds device")
            self._tls_creds_id = '%s_server_tls_creds' % self._tag
            dev = qemu_devices.qdevices.QObject('tls-creds-x509')
            dev.set_param("id", self._tls_creds_id)
            dev.set_param("endpoint", "server")
            dev.set_param("dir", self._image_params['nbd_server_tls_creds'])
            ret = self._vm.devices.simple_hotplug(dev, self._vm.monitor)
            if not ret[1]:
                raise exceptions.TestFail("Failed to hotplug device '%s': %s."
                                          % (dev, ret[0]))

    def start_nbd_server(self):
        """Start internal nbd server"""
        server = {
            'type': 'unix',
            'path': self._image_params['nbd_unix_socket']
        } if self._image_params.get('nbd_unix_socket') else {
            'type': 'inet',
            'host': '0.0.0.0',
            'port': self._image_params.get('nbd_port', '10809')
        }

        logging.info("Start internal nbd server")
        return self._vm.monitor.nbd_server_start(server, self._tls_creds_id)

    def add_nbd_image(self, node_name=None):
        """
        Add an image(to be exported) to internal nbd server.
        :param node_name: block node name, the node might be hotplugged
                          by other utils, or the node has already been
                          present in VM.
        """
        if node_name:
            self._node_name = node_name

        logging.info("Add image node to nbd server")
        return self._vm.monitor.nbd_server_add(
            self._node_name,
            self._image_params.get('nbd_export_name'),
            self._image_params.get('nbd_export_writable'),
            self._image_params.get('nbd_export_bitmap'))

    def remove_nbd_image(self):
        """Remove the exported image from internal nbd server"""
        logging.info("Remove image from nbd server")
        return self._vm.monitor.nbd_server_remove(
            self.get_export_name(),
            self._image_params.get('nbd_remove_mode')
        )

    def stop_nbd_server(self):
        """Stop internal nbd server, it also unregisters all devices"""
        logging.info("Stop nbd server")
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
        self.stop_nbd_server()
