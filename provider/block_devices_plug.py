"""
Module for providing interfaces about plugging block devices.

Available classes:
- BlockDevicesPlug: The class provides interfaces about hot plugging and
                    unplugging block devices.

Available methods:
- hotplug_devs_serial: Hot plug the block devices by serial.
- unplug_devs_serial: Unplug the block devices by serial.
- hotplug_devs_threaded: Hot plug the block devices by threaded.
- unplug_devs_threaded: Unplug the block devices by threaded.

"""

import logging
import multiprocessing
import sys
import threading

from avocado import TestError

from six import reraise
from six.moves import xrange

from virttest import utils_misc
from virttest.qemu_capabilities import Flags
from virttest.qemu_devices import qdevices
from virttest.qemu_devices.utils import (DeviceError, DeviceHotplugError,
                                         DeviceUnplugError)

HOTPLUG, UNPLUG = ('hotplug', 'unplug')
HOTPLUGGED_HBAS = {}
DELETED_EVENT = 'DEVICE_DELETED'
DISK = {'name': 'images', 'media': 'disk'}
CDROM = {'name': 'cdroms', 'media': 'cdrom'}

_LOCK = threading.Lock()


def _verify_plugged_num(action):
    """
    Verify if the number of changed disks is equal to the plugged ones.
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            orig_disks = self._list_all_disks()
            logging.debug('The index of disks before %s:\n %s' % (action, orig_disks))
            result = func(self, *args, **kwargs)
            if self._dev_type != CDROM:
                for dev in HOTPLUGGED_HBAS.values():
                    if dev.get_param('hotplug') == 'off':
                        return result
                if not utils_misc.wait_for(lambda: len(self._imgs) == len(
                        self._list_all_disks() ^ orig_disks), self._timeout, step=1.5):
                    disks_info_win = ('wmic logicaldisk get drivetype,name,description '
                                      '& wmic diskdrive list brief /format:list')
                    disks_info_linux = 'lsblk -a'
                    _session = self.vm.wait_for_login(timeout=360)
                    disks_info = _session.cmd(
                        disks_info_win if self._iswindows else disks_info_linux)
                    logging.debug("The details of disks:\n %s" % disks_info)
                    _session.close()
                    raise TestError(
                        "%s--> Actual: %s disks. Expected: %s disks." %
                        (action, len(self._all_disks ^ orig_disks), len(self._imgs)))
                self._plugged_disks = sorted(
                    [disk.split('/')[-1] for disk in list(self._all_disks ^ orig_disks)])
            return result
        return wrapper
    return decorator


class _PlugThread(threading.Thread):

    """
    Plug Thread that define a plug thread.
    """

    def __init__(self, vm, action, images, monitor, exit_event, bus=None):
        threading.Thread.__init__(self)
        self._action = action
        self._images = images
        self._monitor = monitor
        self._bus = bus
        self._plug_manager = BlockDevicesPlug(vm)
        self.exit_event = exit_event
        self.exc_info = None

    def run(self):
        try:
            args = (self._images, self._monitor)
            if self._bus:
                args = (self._images, self._monitor, self._bus)
            method = "_hotplug_devs" if self._action == HOTPLUG else "_unplug_devs"
            getattr(self._plug_manager, method)(*args)
        except Exception as e:
            logging.error(
                '%s %s failed: %s' % (self._action.capitalize(), self._images, str(e)))
            self.exc_info = sys.exc_info()
            self.exit_event.set()


class _ThreadManager(object):

    """
    Thread Manager that provides interfaces about threads for plugging devices.
    """

    def __init__(self, vm):
        self._vm = vm
        self._threads = []
        self.exit_event = threading.Event()

    def _initial_threads(self, action, imgs, bus=None):
        """ Initial the threads. """
        max_threads = min(len(imgs), 2 * multiprocessing.cpu_count())
        for i in xrange(max_threads):
            mon = self._vm.monitors[i % len(self._vm.monitors)]
            args = (self._vm, action, imgs[i::max_threads], mon, self.exit_event)
            if bus:
                args = (self._vm, action, imgs[i::max_threads], mon, self.exit_event, bus)
            self._threads.append(_PlugThread(*args))

    def _start_threads(self):
        """ Start the threads. """
        for thread in self._threads:
            thread.start()

    def _join_threads(self, timeout):
        """ Join the threads. """
        for thread in self._threads:
            thread.join(timeout)

    def run_threads(self, action, imgs, bus, timeout):
        """ Run the threads. """
        self._initial_threads(action, imgs, bus)
        self._start_threads()
        self._join_threads(timeout)

    def raise_threads(self):
        """ Raise the exception information of threads. """
        for thread in self._threads:
            if thread.exc_info:
                reraise(*thread.exc_info)

    def clean_threads(self):
        """ Clean the env threads. """
        del self.exit_event
        del self._threads[:]


class BlockDevicesPlug(object):

    """
    The Block Devices Plug.
    """

    def __init__(self, vm):
        self.vm = vm
        self._imgs = vm.params.get("images").split()[1:]
        self._hotplugged_devs = {}
        self._unplugged_devs = {}
        self._islinux = vm.params['os_type'] == 'linux'
        self._iswindows = vm.params['os_type'] == 'windows'
        self._plugged_disks = []
        self._orig_disks = set()
        self._all_disks = set()
        self._qmp_outputs = {}
        self._event_devs = []
        self._dev_type = DISK
        self._qdev_type = qdevices.QBlockdevNode if vm.check_capability(
            Flags.BLOCKDEV) else qdevices.QDrive
        self._timeout = 300

    def __getitem__(self, index):
        """ Get the hot plugged disk index. """
        return self._plugged_disks[index]

    def __len__(self):
        """ Get the len of the hot plugged disks. """
        return len(self._plugged_disks)

    def __iter__(self):
        """ Iterate the the hot plugged disks. """
        for disk in self._plugged_disks:
            yield disk

    def _list_all_disks(self):
        """ List all the disks. """
        session = self.vm.wait_for_login(timeout=360)
        if self._islinux:
            self._all_disks = utils_misc.list_linux_guest_disks(session)
        else:
            self._all_disks = set(session.cmd('wmic diskdrive get index').split()[1:])
        session.close()
        return self._all_disks

    def _check_qmp_outputs(self, action):
        """ Check the output of qmp commands. """
        for dev_id in list(self._qmp_outputs.keys()):
            output = self._qmp_outputs.pop(dev_id)
            if output[1] is False:
                raise TestError("Failed to %s device %s." % (action, dev_id))

    def _get_events_deleted(self):
        """ Get the device deleted events. """
        self.event_devs = [img for img in self._unplugged_devs.keys()]
        for event in self.vm.monitor.get_events():
            if DELETED_EVENT in event.get("event") and 'device' in event.get('data'):
                name = event.get('data')['device']
                if name in self.event_devs:
                    self.event_devs.remove(name)
        self.vm.monitor.clear_event(DELETED_EVENT)
        return not self.event_devs

    def _wait_events_deleted(self, timeout=300):
        """
        Wait the events "DEVICE DELETED" to be generated after unplug device.
        """
        if not utils_misc.wait_for(self._get_events_deleted, timeout):
            raise TestError(
                'No \"DEVICE DELETED\" event generated after unplug \"%s\".' %
                (';'.join(self.event_devs)))

    def _create_devices(self, images):
        """ Create the block devcies. """
        self._hotplugged_devs.clear()
        for img in images:
            bus_name = None
            self._hotplugged_devs[img] = []
            img_params = self.vm.params.object_params(img)
            devices_created = getattr(
                self.vm.devices, '%s_define_by_params' % self._dev_type['name'])(
                img, img_params, self._dev_type['media'])

            for dev in reversed(devices_created):
                if dev.get_qid().endswith(img):
                    self._hotplugged_devs[img].insert(0, dev)
                    bus = dev.get_param('bus')
                    if bus:
                        bus_name = bus.rsplit('.')[0]
                # Search the corresponding HBA device to be plugged.
                elif bus_name == dev.get_qid() and dev not in self.vm.devices:
                    self._hotplugged_devs[img].insert(-1, dev)
                    HOTPLUGGED_HBAS[img] = dev
                    break

    def _hotplug_atomic(self, device, monitor, bus=None):
        """ Function hot plug device to devices representation. """
        with _LOCK:
            self.vm.devices.set_dirty()

        with _LOCK:
            if isinstance(device, qdevices.QDevice):
                dev_bus = device.get_param('bus')
                if bus is None:
                    if self.vm.devices.is_pci_device(device['driver']):
                        bus = self.vm.devices.get_buses({'aobject': 'pci.0'})[0]
                    if not isinstance(device.parent_bus, (list, tuple)):
                        device.parent_bus = [device.parent_bus]
                    for parent_bus in device.parent_bus:
                        for _bus in self.vm.devices.get_buses(parent_bus):
                            if _bus.bus_item == 'bus':
                                if dev_bus:
                                    dev_bus_name = dev_bus.rsplit('.')[0]
                                    if _bus.busid:
                                        if dev_bus_name == _bus.busid:
                                            bus = _bus
                                            break
                                else:
                                    bus = _bus
                                    break

                if bus is not None:
                    bus.prepare_hotplug(device)
                    qdev_out = self.vm.devices.insert(device)

            out = device.hotplug(monitor)
            ver_out = device.verify_hotplug(out, monitor)

        if ver_out is False:
            with _LOCK:
                self.vm.devices.set_clean()
            return out, ver_out

        try:
            with _LOCK:
                if device not in self.vm.devices:
                    qdev_out = self.vm.devices.insert(device)
            if not isinstance(qdev_out, list) or len(qdev_out) != 1:
                raise NotImplementedError(
                    "This device %s require to hotplug multiple devices %s, "
                    "which is not supported." % (device, out))
            if ver_out is True:
                with _LOCK:
                    self.vm.devices.set_clean()
        except DeviceError as exc:
            raise DeviceHotplugError(
                device, 'According to qemu_device: %s' % exc, self, ver_out)
        return out, ver_out

    def _unplug_atomic(self, device, monitor):
        """ Function unplug device to devices representation. """
        device = self.vm.devices[device]
        with _LOCK:
            self.vm.devices.set_dirty()

        out = device.unplug(monitor)
        if not utils_misc.wait_for(lambda: device.verify_unplug(
                out, monitor) is True, first=1, step=5, timeout=60):
            with _LOCK:
                self.vm.devices.set_clean()
            return out, device.verify_unplug(out, monitor)
        ver_out = device.verify_unplug(out, monitor)

        try:
            device.unplug_hook()
            drive = device.get_param("drive")
            if drive:
                if self.vm.check_capability(Flags.BLOCKDEV):
                    format_node = self.vm.devices[drive]
                    nodes = [format_node]
                    nodes.extend((n for n in format_node.get_child_nodes()))
                    for node in nodes:
                        if not node.verify_unplug(node.unplug(monitor), monitor):
                            raise DeviceUnplugError(
                                node, "Failed to unplug blockdev node.", self)
                        with _LOCK:
                            self.vm.devices.remove(node, True if isinstance(
                                node, qdevices.QBlockdevFormatNode) else False)
                        if not isinstance(node, qdevices.QBlockdevFormatNode):
                            format_node.del_child_node(node)
                else:
                    with _LOCK:
                        self.vm.devices.remove(drive)

            with _LOCK:
                self.vm.devices.remove(device, True)
            if ver_out is True:
                with _LOCK:
                    self.vm.devices.set_clean()
            elif out is False:
                raise DeviceUnplugError(
                    device, "Device wasn't unplugged in qemu, but it was "
                            "unplugged in device representation.", self)
        except (DeviceError, KeyError) as exc:
            device.unplug_unhook()
            raise DeviceUnplugError(device, exc, self)
        return out, ver_out

    def _plug_devs(self, action, devices_dict, monitor, bus=None):
        """ Plug devices. """
        for img, devices in devices_dict.items():
            for device in devices:
                args = (device, monitor) if bus is None else (device, monitor, bus)
                self._qmp_outputs[device.get_qid()] = getattr(
                    self, '_%s_atomic' % action)(*args)

    def _hotplug_devs(self, images, monitor, bus=None):
        """
        Hot plug the block devices which are defined by images.
        """
        logging.info("Start to hotplug devices \"%s\" by monitor %s." % (
            ' '.join(images), monitor.name))
        self._create_devices(images)
        self._plug_devs(HOTPLUG, self._hotplugged_devs, monitor, bus)

    def _unplug_devs(self, images, monitor):
        """
        Unplug the block devices which are defined by images.
        """
        self._unplugged_devs.clear()
        devs = [dev for dev in self.vm.devices if isinstance(dev, qdevices.QDevice)]
        for img in images:
            self._unplugged_devs[img] = []
            for dev in devs:
                if dev.get_qid() == img:
                    self._unplugged_devs[img].append(dev)
                    break
            else:
                raise TestError('No such device \'%s\' in VM\'s devices.' % img)

        # Search the corresponding HBA device to be unplugged.
        for img in list(self._unplugged_devs.keys()):
            _dev = self._unplugged_devs[img][0]
            _dev_bus = _dev.get_param('bus')
            if _dev_bus:
                bus_name = _dev_bus.rsplit('.')[0]
                for parent_bus in _dev.parent_bus:
                    for bus in self.vm.devices.get_buses(parent_bus, True):
                        if bus_name == bus.busid.rsplit('.')[0]:
                            if len(bus) == 1 and img in HOTPLUGGED_HBAS:
                                self._unplugged_devs[img].append(HOTPLUGGED_HBAS.pop(img))
                            break

        logging.info("Start to unplug devices \"%s\" by monitor %s." %
                     (' '.join(images), monitor.name))
        self._plug_devs(UNPLUG, self._unplugged_devs, monitor)

    def _plug_devs_threads(self, action, images, bus, timeout):
        """ Threads that plug blocks devices. """
        self._orig_disks = self._list_all_disks()
        if images:
            self._imgs = images.split()
        th_mgr = _ThreadManager(self.vm)
        th_mgr.run_threads(action, self._imgs, bus, timeout)
        if th_mgr.exit_event.is_set():
            th_mgr.raise_threads()
        th_mgr.clean_threads()
        logging.info("All %s threads finished." % action)

    @_verify_plugged_num(action=HOTPLUG)
    def hotplug_devs_serial(self, images=None, monitor=None, bus=None, timeout=300):
        """
        Hot plug the block devices by serial.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param monitor: Monitor from vm.
        :type monitor: qemu_monitor.Monitor
        :param bus: The bus to be plugged into
        :type bus: qdevice.QSparseBus
        :param timeout: Timeout for hot plugging.
        :type timeout: float
        """
        self._timeout = timeout
        if monitor is None:
            monitor = self.vm.monitor
        if images:
            self._imgs = [img for img in images.split()]
        if set(self._imgs) <= set(self.vm.params['cdroms'].split()):
            self._dev_type = CDROM
        self._hotplug_devs(self._imgs, monitor, bus)
        self._check_qmp_outputs(HOTPLUG)

    @_verify_plugged_num(action=UNPLUG)
    def unplug_devs_serial(self, images=None, monitor=None, timeout=300):
        """
        Unplug the block devices by serial.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param monitor: Monitor from vm.
        :type monitor: qemu_monitor.Monitor
        :param timeout: Timeout for hot plugging.
        :type timeout: int
        """
        self._timeout = timeout
        if monitor is None:
            monitor = self.vm.monitor
        if images:
            self._imgs = [img for img in images.split()]
        if set(self._imgs) <= set(self.vm.params['cdroms'].split()):
            self._dev_type = CDROM
        self._unplug_devs(self._imgs, monitor)
        self._check_qmp_outputs(UNPLUG)
        self._wait_events_deleted(timeout)

    @_verify_plugged_num(action=UNPLUG)
    def hotplug_devs_threaded(self, images=None, timeout=300, bus=None):
        """
        Hot plug the block devices by threaded.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param bus: The bus to be plugged into
        :type bus: qdevice.QSparseBus
        :param timeout: Timeout for hot plugging.
        :type timeout: float
        """
        self._timeout = timeout
        self._plug_devs_threads(HOTPLUG, images, bus, timeout)
        self._check_qmp_outputs(HOTPLUG)

    @_verify_plugged_num(action=UNPLUG)
    def unplug_devs_threaded(self, images=None, timeout=300):
        """
        Unplug the block devices by threaded.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param timeout: Timeout for hot plugging.
        :type timeout: int
        """
        self._timeout = timeout
        self._plug_devs_threads(UNPLUG, images, None, timeout)
        self._check_qmp_outputs(UNPLUG)
        self._wait_events_deleted(timeout)
