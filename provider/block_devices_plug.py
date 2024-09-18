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
import time

from avocado import TestError
from six import reraise
from six.moves import xrange
from virttest import utils_misc
from virttest.qemu_capabilities import Flags
from virttest.qemu_devices import qdevices
from virttest.qemu_devices.utils import (
    DeviceError,
    DeviceHotplugError,
    DeviceUnplugError,
)
from virttest.qemu_monitor import MonitorLockError

LOG_JOB = logging.getLogger("avocado.test")

HOTPLUG, UNPLUG = ("hotplug", "unplug")
HOTPLUGGED_HBAS = {}
DELETED_EVENT = "DEVICE_DELETED"
DISK = {"name": "images", "media": "disk"}
CDROM = {"name": "cdroms", "media": "cdrom"}

_LOCK = threading.Lock()
_QMP_OUTPUT = {}


def _verify_plugged_num(action):
    """
    Verify if the number of changed disks is equal to the plugged ones.
    """

    def decorator(func):
        def wrapper(self, *args, **kwargs):
            orig_disks = self._list_all_disks()
            LOG_JOB.debug("The index of disks before %s:\n %s", action, orig_disks)
            result = func(self, *args, **kwargs)
            if self._dev_type != CDROM:
                for dev in HOTPLUGGED_HBAS.values():
                    if dev.get_param("hotplug") == "off":
                        return result
                if not utils_misc.wait_for(
                    lambda: len(self._imgs) == len(self._list_all_disks() ^ orig_disks),
                    self._timeout,
                    step=1.5,
                ):
                    disks_info_win = (
                        "wmic logicaldisk get drivetype,name,description "
                        "& wmic diskdrive list brief /format:list"
                    )
                    disks_info_linux = "lsblk -a"
                    _session = self.vm.wait_for_login(timeout=360)
                    disks_info = _session.cmd(
                        disks_info_win if self._iswindows else disks_info_linux
                    )
                    LOG_JOB.debug("The details of disks:\n %s", disks_info)
                    _session.close()
                    raise TestError(
                        "%s--> Actual: %s disks. Expected: %s disks."
                        % (action, len(self._all_disks ^ orig_disks), len(self._imgs))
                    )
                self._plugged_disks = sorted(
                    [disk.split("/")[-1] for disk in list(self._all_disks ^ orig_disks)]
                )
            return result

        return wrapper

    return decorator


class _PlugThread(threading.Thread):
    """
    Plug Thread that define a plug thread.
    """

    def __init__(self, vm, action, images, monitor, exit_event, bus=None, interval=0):
        threading.Thread.__init__(self)
        self._action = action
        self._images = images
        self._monitor = monitor
        self._bus = bus
        self._interval = interval
        self._plug_manager = BlockDevicesPlug(vm)
        self.exit_event = exit_event
        self.exc_info = None

    def run(self):
        try:
            args = (self._images, self._monitor, self._interval)
            if self._action == HOTPLUG:
                bus = self._bus if self._bus else None
                args = (self._images, self._monitor, bus, self._interval)
            method = "_hotplug_devs" if self._action == HOTPLUG else "_unplug_devs"
            getattr(self._plug_manager, method)(*args)
        except Exception as e:
            LOG_JOB.error(
                "%s %s failed: %s", self._action.capitalize(), self._images, str(e)
            )
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

    def _initial_threads(self, action, imgs, bus=None, interval=0):
        """Initial the threads."""
        max_threads = min(len(imgs), 2 * multiprocessing.cpu_count())
        for i in xrange(max_threads):
            mon = self._vm.monitors[i % len(self._vm.monitors)]
            args = (
                self._vm,
                action,
                imgs[i::max_threads],
                mon,
                self.exit_event,
                bus,
                interval,
            )
            self._threads.append(_PlugThread(*args))

    def _start_threads(self):
        """Start the threads."""
        for thread in self._threads:
            thread.start()

    def _join_threads(self, timeout):
        """Join the threads."""
        for thread in self._threads:
            thread.join(timeout)

    def run_threads(self, action, imgs, bus, timeout, interval=0):
        """Run the threads."""
        self._initial_threads(action, imgs, bus, interval)
        self._start_threads()
        self._join_threads(timeout)

    def raise_threads(self):
        """Raise the exception information of threads."""
        for thread in self._threads:
            if thread.exc_info:
                reraise(*thread.exc_info)

    def clean_threads(self):
        """Clean the env threads."""
        del self.exit_event
        del self._threads[:]


class BlockDevicesPlug(object):
    """
    The Block Devices Plug.
    """

    ACQUIRE_LOCK_TIMEOUT = 20
    VERIFY_UNPLUG_TIMEOUT = 60

    def __init__(self, vm):
        self.vm = vm
        self._imgs = vm.params.get("images").split()[1:]
        self._hotplugged_devs = {}
        self._unplugged_devs = {}
        self._islinux = vm.params["os_type"] == "linux"
        self._iswindows = vm.params["os_type"] == "windows"
        self._plugged_disks = []
        self._orig_disks = set()
        self._all_disks = set()
        self._event_devs = []
        self._dev_type = DISK
        self._qdev_type = (
            qdevices.QBlockdevNode
            if vm.check_capability(Flags.BLOCKDEV)
            else qdevices.QDrive
        )
        self._timeout = 300
        self._interval = 0
        self._qemu_version = self.vm.devices.qemu_version

    def __getitem__(self, index):
        """Get the hot plugged disk index."""
        return self._plugged_disks[index]

    def __len__(self):
        """Get the len of the hot plugged disks."""
        return len(self._plugged_disks)

    def __iter__(self):
        """Iterate the the hot plugged disks."""
        for disk in self._plugged_disks:
            yield disk

    def _list_all_disks(self):
        """List all the disks."""
        session = self.vm.wait_for_login(timeout=360)
        if self._islinux:
            self._all_disks = utils_misc.list_linux_guest_disks(session)
        else:
            self._all_disks = set(session.cmd("wmic diskdrive get index").split()[1:])
        session.close()
        return self._all_disks

    def _check_qmp_outputs(self, action):
        """Check the output of qmp commands."""
        for dev_id in list(_QMP_OUTPUT.keys()):
            output = _QMP_OUTPUT.pop(dev_id)
            if output[1] is False:
                err = "Failed to %s device %s. " % (action, dev_id)
                if not output[0] and action == "unplug":
                    err += "No deleted event generated and %s still in qtree" % dev_id
                else:
                    err += output[0]
                raise TestError(err)

    def _get_events_deleted(self):
        """Get the device deleted events."""
        self.event_devs = [img for img in self._unplugged_devs.keys()]
        for event in self.vm.monitor.get_events():
            if DELETED_EVENT in event.get("event") and "device" in event.get("data"):
                name = event.get("data")["device"]
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
                'No "DEVICE DELETED" event generated after unplug "%s".'
                % (";".join(self.event_devs))
            )

    def _create_devices(self, images, pci_bus={"aobject": "pci.0"}):
        """Create the block devcies."""
        self._hotplugged_devs.clear()
        for img in images:
            bus_name = None
            self._hotplugged_devs[img] = []
            img_params = self.vm.params.object_params(img)
            devices_created = getattr(
                self.vm.devices, "%s_define_by_params" % self._dev_type["name"]
            )(img, img_params, self._dev_type["media"], pci_bus=pci_bus)

            for dev in reversed(devices_created):
                qid = dev.get_qid()
                if (
                    isinstance(dev, qdevices.QObject)
                    and dev.get_param("backend") == "secret"
                    and qid.startswith("%s_" % img)
                ):
                    self._hotplugged_devs[img].insert(0, dev)
                elif qid.endswith("_%s" % img) or qid == img:
                    self._hotplugged_devs[img].insert(0, dev)
                    bus = dev.get_param("bus")
                    if bus:
                        bus_name = bus.rsplit(".")[0]
                # Search the corresponding HBA device to be plugged.
                elif bus_name == dev.get_qid() and dev not in self.vm.devices:
                    self._hotplugged_devs[img].insert(-1, dev)
                    HOTPLUGGED_HBAS[img] = dev

    def _plug(self, plug_func, monitor, action):
        end = time.time() + self.ACQUIRE_LOCK_TIMEOUT
        while time.time() < end:
            try:
                return (
                    plug_func(monitor)
                    if action == UNPLUG
                    else plug_func(monitor, self._qemu_version)
                )
            except MonitorLockError:
                pass
        else:
            return (
                plug_func(monitor)
                if action == UNPLUG
                else plug_func(monitor, self._qemu_version)
            )

    def _hotplug_atomic(self, device, monitor, bus=None):
        """Function hot plug device to devices representation."""
        self.vm.devices.set_dirty()

        qdev_out = ""
        if isinstance(device, qdevices.QDevice):
            dev_bus = device.get_param("bus")
            if bus is None:
                if self.vm.devices.is_pci_device(device["driver"]):
                    bus = self.vm.devices.get_buses({"aobject": "pci.0"})[0]
                if not isinstance(device.parent_bus, (list, tuple)):
                    device.parent_bus = [device.parent_bus]
                for parent_bus in device.parent_bus:
                    for _bus in self.vm.devices.get_buses(parent_bus):
                        if _bus.bus_item == "bus":
                            if dev_bus:
                                dev_bus_name = dev_bus.rsplit(".")[0]
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

        out = self._plug(device.hotplug, monitor, HOTPLUG)
        ver_out = device.verify_hotplug(out, monitor)
        if ver_out is False:
            self.vm.devices.set_clean()
            return out, ver_out

        try:
            if device not in self.vm.devices:
                qdev_out = self.vm.devices.insert(device)
            if not isinstance(qdev_out, list) or len(qdev_out) != 1:
                raise NotImplementedError(
                    "This device %s require to hotplug multiple devices %s, "
                    "which is not supported." % (device, out)
                )
            if ver_out is True:
                self.vm.devices.set_clean()
        except DeviceError as exc:
            raise DeviceHotplugError(
                device, "According to qemu_device: %s" % exc, self, ver_out
            )
        return out, ver_out

    def _unplug_atomic(self, device, monitor):
        """Function unplug device to devices representation."""
        device = self.vm.devices[device]
        self.vm.devices.set_dirty()

        out = self._plug(device.unplug, monitor, UNPLUG)
        if not utils_misc.wait_for(
            lambda: device.verify_unplug(out, monitor) is True,
            first=1,
            step=5,
            timeout=self.VERIFY_UNPLUG_TIMEOUT,
        ):
            self.vm.devices.set_clean()
            return out, device.verify_unplug(out, monitor)
        ver_out = device.verify_unplug(out, monitor)

        try:
            device.unplug_hook()
            drive = device.get_param("drive")
            self.vm.devices.remove(device, True)
            if drive:
                if self.vm.check_capability(Flags.BLOCKDEV):
                    # top node
                    node = self.vm.devices[drive]
                    nodes = [node]

                    # Build the full nodes list
                    for node in nodes:
                        child_nodes = node.get_child_nodes()
                        nodes.extend(child_nodes)

                    for node in nodes:
                        parent_node = node.get_parent_node()
                        child_nodes = node.get_child_nodes()
                        recursive = True if len(child_nodes) > 0 else False
                        if not node.verify_unplug(
                            self._plug(node.unplug, monitor, UNPLUG), monitor
                        ):
                            raise DeviceUnplugError(
                                node, "Failed to unplug blockdev node.", self
                            )
                        self.vm.devices.remove(node, recursive)
                        if parent_node:
                            parent_node.del_child_node(node)
                else:
                    self.vm.devices.remove(drive)

            if ver_out is True:
                self.vm.devices.set_clean()
            elif out is False:
                raise DeviceUnplugError(
                    device,
                    "Device wasn't unplugged in qemu, but it was "
                    "unplugged in device representation.",
                    self,
                )
        except (DeviceError, KeyError) as exc:
            device.unplug_unhook()
            raise DeviceUnplugError(device, exc, self)
        return out, ver_out

    def _plug_devs(self, action, devices_dict, monitor, bus=None, interval=0):
        """Plug devices."""
        for img, devices in devices_dict.items():
            for device in devices:
                args = (device, monitor)
                if (
                    isinstance(device, qdevices.QDevice)
                    and bus is not None
                    and self.vm.devices.is_pci_device(device["driver"])
                ):
                    args += (bus,)
                with _LOCK:
                    _QMP_OUTPUT[device.get_qid()] = getattr(
                        self, "_%s_atomic" % action
                    )(*args)
                time.sleep(interval)

    def _hotplug_devs(self, images, monitor, bus=None, interval=0):
        """
        Hot plug the block devices which are defined by images.
        """
        LOG_JOB.info(
            'Start to hotplug devices "%s" by monitor %s.',
            " ".join(images),
            monitor.name,
        )
        args = (images, {"aobject": "pci.0" if bus is None else bus.aobject})
        self._create_devices(*args)
        self._plug_devs(HOTPLUG, self._hotplugged_devs, monitor, bus, interval)

    def _unplug_devs(self, images, monitor, interval=0):
        """
        Unplug the block devices which are defined by images.
        """
        self._unplugged_devs.clear()
        devs = [
            dev
            for dev in self.vm.devices
            if isinstance(dev, (qdevices.QDevice, qdevices.QObject))
        ]
        for img in images:
            self._unplugged_devs[img] = []
            for dev in devs:
                qid = dev.get_qid()
                if qid == img or qid.startswith("%s_" % img):
                    self._unplugged_devs[img].insert(0, dev)
                    if qid == img:
                        break
            else:
                raise TestError("No such device '%s' in VM's devices." % img)

        # Search the corresponding HBA device to be unplugged.
        for img in list(self._unplugged_devs.keys()):
            _dev = next((_ for _ in self._unplugged_devs[img] if _.get_qid() == img))
            _dev_bus = _dev.get_param("bus")
            if _dev_bus:
                bus_name = _dev_bus.rsplit(".")[0]
                for parent_bus in _dev.parent_bus:
                    for bus in self.vm.devices.get_buses(parent_bus, True):
                        if bus_name == bus.busid.rsplit(".")[0]:
                            if len(bus) == 1 and img in HOTPLUGGED_HBAS:
                                self._unplugged_devs[img].append(
                                    HOTPLUGGED_HBAS.pop(img)
                                )
                            break

        LOG_JOB.info(
            'Start to unplug devices "%s" by monitor %s.',
            " ".join(images),
            monitor.name,
        )
        self._plug_devs(UNPLUG, self._unplugged_devs, monitor, interval=interval)

    def _plug_devs_threads(self, action, images, bus, timeout, interval=0):
        """Threads that plug blocks devices."""
        self._orig_disks = self._list_all_disks()
        if images:
            self._imgs = images.split()
        th_mgr = _ThreadManager(self.vm)
        th_mgr.run_threads(action, self._imgs, bus, timeout, interval=interval)
        if th_mgr.exit_event.is_set():
            th_mgr.raise_threads()
        th_mgr.clean_threads()
        LOG_JOB.info("All %s threads finished.", action)

    @_verify_plugged_num(action=HOTPLUG)
    def hotplug_devs_serial(
        self, images=None, monitor=None, bus=None, timeout=300, interval=0
    ):
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
        :param interval: Interval time for hot plugging.
        :type interval: int
        """
        self._timeout = timeout
        if monitor is None:
            monitor = self.vm.monitor
        if images:
            self._imgs = [img for img in images.split()]
        if set(self._imgs) <= set(self.vm.params["cdroms"].split()):
            self._dev_type = CDROM
        self._hotplug_devs(self._imgs, monitor, bus, interval)
        self._check_qmp_outputs(HOTPLUG)

    @_verify_plugged_num(action=UNPLUG)
    def unplug_devs_serial(self, images=None, monitor=None, timeout=300, interval=0):
        """
        Unplug the block devices by serial.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param monitor: Monitor from vm.
        :type monitor: qemu_monitor.Monitor
        :param timeout: Timeout for hot plugging.
        :type timeout: int
        :param interval: Interval time for hot plugging.
        :type interval: int
        """
        self._timeout = timeout
        if monitor is None:
            monitor = self.vm.monitor
        if images:
            self._imgs = [img for img in images.split()]
        if set(self._imgs) <= set(self.vm.params["cdroms"].split()):
            self._dev_type = CDROM
        self._unplug_devs(self._imgs, monitor, interval)
        self._check_qmp_outputs(UNPLUG)
        self._wait_events_deleted(timeout)

    @_verify_plugged_num(action=UNPLUG)
    def hotplug_devs_threaded(self, images=None, timeout=300, bus=None, interval=0):
        """
        Hot plug the block devices by threaded.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param bus: The bus to be plugged into
        :type bus: qdevice.QSparseBus
        :param timeout: Timeout for hot plugging.
        :type timeout: float
        :param interval: Interval time for hot plugging.
        :type interval: int
        """
        self._timeout = timeout
        self._plug_devs_threads(HOTPLUG, images, bus, timeout, interval)
        self._check_qmp_outputs(HOTPLUG)

    @_verify_plugged_num(action=UNPLUG)
    def unplug_devs_threaded(self, images=None, timeout=300, interval=0):
        """
        Unplug the block devices by threaded.

        :param images: Image or cdrom tags, e.g, "stg0" or "stg0 stg1 stg3".
        :type images: str
        :param timeout: Timeout for unplugging.
        :type timeout: int
        :param interval: Interval time for unplugging.
        :type interval: int
        """
        self._timeout = timeout
        self._plug_devs_threads(UNPLUG, images, None, timeout, interval)
        self._check_qmp_outputs(UNPLUG)
        self._wait_events_deleted(timeout)
