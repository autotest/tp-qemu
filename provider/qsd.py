"""
Module for QSD and relevant device operation.

QSD means qemu-storage-daemon. It provides disk image
functionality from QEMU.
The main class is QsdDaemonDev, The example show the main
configuration and common usage of QsdDaemonDev:

# Declare QSD named qsd1 and its export images, attributes and type.

qsd_namespaces = qsd1
qsd_images_qsd1 = "stg1 stg2"
qsd_cmd_lines_qsd1 += " --object iothread,id=iothread0;"

#### Declare qsd image stg1 attributes and export with vhost-user-blk
qsd_image_protocol_stg1 = {"cache":{"direct":true,"no-flush":false}}
qsd_image_format_stg1 = {"driver":"qcow2"}
qsd_image_filter_stg1 = {"throttle":"throttle_grp1"}
qsd_image_export_stg1 = {"type":"vhost-user-blk","iothread":"iothread0"}

#### Declare qsd image stg2 attributes and export with nbd inet
qsd_image_export_nbd_stg2 = {"type":"inet","port":"9000"}
qsd_image_export_stg2 = {"type":"nbd"}

### Declare qsd image stg1 created/removed by qsd
qsd_create_image_stg1 = yes
qsd_remove_image_stg1 = yes

# Create a QSD named qsd1
qsd = QsdDaemonDev("qsd1", params)
# Start the QSD
qsd.start_daemon()
# QSD operation via mointor of QSD
qsd.monitor.cmd("query-block-exports")
# Stop the QSD
qsd.stop_daemon()
"""

import copy
import json
import logging
import os
import re
import signal
import subprocess
from enum import Enum, auto

from avocado.utils import process
from virttest import data_dir, qemu_monitor, qemu_storage, utils_misc
from virttest.qemu_capabilities import Capabilities
from virttest.qemu_devices import qdevices
from virttest.qemu_devices.qdevices import QDaemonDev, QUnixSocketBus
from virttest.storage import get_image_filename
from virttest.utils_params import Params

LOG_JOB = logging.getLogger("avocado.test")


class Flags(Enum):
    """Enumerate the flags of QSD capabilities."""

    DAEMONIZE = auto()
    PIDFILE = auto()


class QsdError(Exception):
    """Generic QSD Error."""

    pass


def add_vubp_into_boot(img_name, params, addr=15, opts=""):
    """Add vhost-user-blk-pci device into boot command line"""
    devs = create_vubp_devices(None, img_name, params)
    cmd = ""
    for dev in devs:
        cmd += " %s" % dev.cmdline()
    if cmd:
        machine_type = params.get("machine_type", "")
        if machine_type.startswith("q35") or machine_type.startswith("arm64"):
            busid = "pcie_vubp_root_port_%d" % addr
            bus = "-device pcie-root-port,id=%s,bus=pcie.0,addr=%d " % (busid, addr)
            cmd = bus + cmd + ",bus=%s" % busid
        elif "i440fx" in machine_type or machine_type == "pc":
            cmd += ",bus=pci.0,addr=%d" % addr

        cmd += opts

        params["extra_params"] = cmd
        LOG_JOB.info("Ready add %s into VM command line", cmd)
        return cmd


def get_qsd_name_by_image(img_name, params):
    """Get QSD name by image"""
    if params.get("drive_format_%s" % img_name) != "vhost-user-blk-pci":
        return
    qsd_name = ""

    for qsd in params["qsd_namespaces"].split():
        qsd_imgs = params.object_params(qsd).get("qsd_images", "").split()
        if img_name in qsd_imgs:
            qsd_name = qsd
            break
    return qsd_name


def create_vubp_devices(vm, img_name, params, bus=None):
    """Create vhost-user-blk-pci relevant devices"""
    qsd_name = get_qsd_name_by_image(img_name, params)
    if not qsd_name:
        raise QsdError("Can not find QSD")

    qsd_params = params.object_params(qsd_name)
    qsd_basedir = qsd_params.get(
        "qsd_basedir", data_dir.get_data_dir() + "/qsd/%s" % qsd_name
    )

    qid = "qsd_%s" % qsd_name
    img_sock = "%s/%s_vhost_user_%s.sock" % (qsd_basedir, qsd_name, img_name)
    devices = []
    if vm and not vm.devices.get_by_qid(qid):
        # Declare virtual QSD daemon
        qsd = qdevices.QDaemonDev(
            "qsd",
            aobject=qsd_name,
            child_bus=qdevices.QUnixSocketBus(img_sock, qsd_name),
        )
        vm.devices.insert(qsd)

    machine_type = params.get("machine_type", "")
    qbus_type = "PCI"
    if machine_type.startswith("q35") or machine_type.startswith("arm64"):
        qbus_type = "PCIE"

    char_params = Params()
    char_params["backend"] = "socket"
    char_params["id"] = "char_qsd_%s" % qsd_name
    char_params["path"] = img_sock
    sock_bus = {"busid": img_sock}
    char = qdevices.CharDevice(char_params, parent_bus=sock_bus)
    char.set_param("server", "off")
    char.set_aid(char_params["id"])
    devices.append(char)

    qdriver = "vhost-user-blk-pci"

    if bus is None:
        bus = {"type": qbus_type}

    dev_params = {"id": "vubp_%s" % img_name, "chardev": char.get_qid()}
    vubp_driver_props = json.loads(params.get("image_vubp_props_%s" % img_name, "{}"))
    dev_params.update(vubp_driver_props)
    vubp = qdevices.QDevice(qdriver, params=dev_params, parent_bus=bus)
    vubp.set_aid(dev_params["id"])
    devices.append(vubp)
    LOG_JOB.info("create_vubp_devices %s %s", img_name, devices)
    return devices


def plug_vubp_devices(vm, img_name, params, bus=None):
    """Hotplug vhost-user-blk-pci into VM"""
    LOG_JOB.info("Ready plug vubp image:%s", img_name)

    devs = create_vubp_devices(vm, img_name, params, bus)
    for dev in devs:
        vm.devices.simple_hotplug(dev, vm.monitor)


def unplug_vubp_devices(vm, img_name, params, bus=None):
    """Unplug vhost-user-blk-pci from VM"""
    LOG_JOB.info("Ready unplug vubp image:%s", img_name)
    devs = create_vubp_devices(vm, img_name, params, bus)
    devs = devs[::-1]
    for dev in devs:
        cache_dev = vm.devices.get_by_qid(dev.get_qid())
        if len(cache_dev):
            vm.devices.simple_unplug(cache_dev[0], vm.monitor)
        else:
            # Force unplug device by raw QMP command
            if not dev.verify_unplug(None, vm.monitor):
                out = dev.unplug(vm.monitor)
                utils_misc.wait_for(
                    lambda: dev.verify_unplug(out, vm.monitor) is True,
                    first=1,
                    step=5,
                    timeout=20,
                )
            else:
                LOG_JOB.info("Ignore device %s Can not be found", dev.get_qid())


class QsdDaemonDev(QDaemonDev):
    # Default data struct of raw image data.
    raw_image_data = {
        "protocol": {
            "driver": "file",
            "node-name": "tbd",
            "filename": "tbd",
            "auto-read-only": True,
            "discard": "unmap",
        },
        "format": {"driver": "raw", "node-name": "tbd", "file": "tbd"},
        "filter": {"driver": None, "node-name": "tbd", "file": "tbd"},
        "name": "",
        "unix": {"type": "unix", "path": "tbd"},
        "inet": {"type": "inet", "host": "0.0.0.0"},
        "nbd-server": {"addr": {}},
        "export": {"type": "", "id": "", "node-name": "", "writable": True},
        "image_object": None,
    }

    def __init__(self, name, params):
        qsd_params = params.object_params(name)
        basedir = qsd_params.get(
            "qsd_basedir", data_dir.get_data_dir() + "/qsd/%s" % name
        )
        if not os.path.exists(basedir):
            LOG_JOB.info("Create QSD basedir %s", basedir)
            os.makedirs(basedir)

        binary = qsd_params.get("qsd_binary", "/usr/bin/qemu-storage-daemon")
        sock_path = qsd_params.get(
            "qsd_sock_path", "%s/%s_monitor.sock" % (basedir, name)
        )
        qsd_monitor_id = "qsd_monitor_%s" % name
        qid = "qsd_%s" % name
        super(QsdDaemonDev, self).__init__(
            "QSD", aobject=name, child_bus=QUnixSocketBus(qid, qid)
        )
        self.name = name
        self.basedir = basedir
        self.monitor = None
        self.qsd_params = qsd_params.copy()
        self.qsd_params["monitor_filename"] = sock_path
        self.binary = binary
        self.sock_path = sock_path
        self.qsd_monitor_id = qsd_monitor_id
        self.qsd_version = process.run(
            "%s -V" % binary, verbose=False, ignore_status=True, shell=True
        ).stdout_text.split()[2]
        self.__qsd_help = process.run(
            "%s -h" % binary, verbose=False, ignore_status=True, shell=True
        ).stdout_text

        LOG_JOB.info(self.qsd_version)
        self.caps = Capabilities()
        self._probe_capabilities()
        self.images = {}
        self.daemonize = False
        self.pidfile = None
        self.pid = None

    def _remove_images(self):
        for img in self.images.values():
            # The images will be removed which created by QSD
            if img["image_object"]:
                LOG_JOB.info("QSD ready to remove image:%s", img["name"])
                params = self.qsd_params.object_params(img["name"])
                # Remove image except declare un-remove.
                if params.get("qsd_remove_image", "yes") != "no":
                    img["image_object"].remove()

    def _fulfil_image_props(self, name, params):
        """Fulfil image property and prepare image file"""
        img = copy.deepcopy(QsdDaemonDev.raw_image_data)
        img["name"] = name
        img["protocol"]["node-name"] = "prot_" + name
        filename = get_image_filename(params, data_dir.get_data_dir())
        img["protocol"]["filename"] = filename
        img["format"]["node-name"] = "fmt_" + name
        img["format"]["file"] = img["protocol"]["node-name"]
        img["format"]["driver"] = params.get("image_format")
        img["filter"]["node-name"] = "flt_" + name
        img["filter"]["file"] = img["format"]["node-name"]

        img["protocol"].update(json.loads(params.get("qsd_image_protocol", "{}")))
        img["format"].update(json.loads(params.get("qsd_image_format", "{}")))
        img["filter"].update(json.loads(params.get("qsd_image_filter", "{}")))

        img["export"]["id"] = "id_" + name
        img["export"]["node-name"] = (
            img["filter"]["node-name"]
            if img["filter"]["driver"]
            else img["format"]["node-name"]
        )
        img["export"].update(json.loads(params.get("qsd_image_export", "{}")))

        if img["export"]["type"] == "nbd":
            # The name is necessary. empty value to simply setting in nbd client
            img["export"]["name"] = ""
            addr = json.loads(params.get("qsd_image_export_nbd", '{"type":"unix"'))

            img[addr["type"]].update(addr)
            if addr["type"] == "unix":
                if not img[addr["type"]]["path"]:
                    img[addr["type"]]["path"] = "%s/%s_nbd_%s.sock" % (
                        self.basedir,
                        self.name,
                        name,
                    )
            img["nbd-server"]["addr"].update(img[addr["type"]])

        elif img["export"]["type"] == "vhost-user-blk":
            img["unix"]["path"] = "%s/%s_vhost_user_%s.sock" % (
                self.basedir,
                self.name,
                name,
            )
            img["export"]["addr"] = img["unix"]
        else:
            raise QsdError("Unknown export type %s " % img["export"]["type"])

        # Prepare image
        image_created = False

        if name in params.get("images").split():
            if (
                params.get("force_create_image") == "yes"
                or params.get("create_image") == "yes"
            ):
                image_created = True

        if image_created:
            LOG_JOB.info("QSD skip to create image %s ", name)
        else:
            # Record the images are maintained by QSD.
            obj = qemu_storage.QemuImg(params, data_dir.get_data_dir(), name)
            if params.get("qsd_create_image", "yes") == "yes":
                LOG_JOB.info("QSD ready to create image %s", name)
                _, result = obj.create(params)
                if result.exit_status != 0:
                    raise QsdError("Failed create image %s " % name)
            img["image_object"] = obj

        self.images.update({name: img})
        return img

    def has_option(self, option):
        """
        :param option: Desired option
        :return: Is the desired option supported by current qemu?
        """
        return bool(re.search(r"%s" % option, self.__qsd_help, re.MULTILINE))

    def _probe_capabilities(self):
        """Probe capabilities."""

        if self.has_option("--daemonize"):
            LOG_JOB.info("--daemonize")
            self.caps.set_flag(Flags.DAEMONIZE)
        if self.has_option("--pidfile"):
            LOG_JOB.info("--pidfile")
            self.caps.set_flag(Flags.PIDFILE)

    def get_pid(self):
        """Get QSD pid"""
        if self.daemonize:
            return self.pid
        if self.daemon_process:
            return self.daemon_process.get_pid()

    def start_daemon(self):
        """Start the QSD daemon in background."""
        params = self.qsd_params.object_params(self.name)
        # check exist QSD
        get_pid_cmd = "ps -e ww|grep qemu-storage-d|grep %s|" % self.sock_path
        get_pid_cmd += "grep -v grep|awk '{print $1}'"
        pid = process.system_output(get_pid_cmd, shell=True).decode()

        if pid:
            if params.get("qsd_force_create", "yes") == "yes":
                # Kill exist QSD
                LOG_JOB.info("Find running QSD:%s, force killing", pid)
                utils_misc.kill_process_tree(int(pid), 9, timeout=60)
            else:
                raise QsdError("Find running QSD:%s" % pid)

        # QSD monitor
        qsd_cmd = "%s --chardev socket,server=on,wait=off,path=%s,id=%s" % (
            self.binary,
            self.sock_path,
            self.qsd_monitor_id,
        )
        qsd_cmd += " --monitor chardev=%s,mode=control " % self.qsd_monitor_id

        # QSD raw command lines
        cmds = self.qsd_params.get("qsd_cmd_lines", "")
        for cmd in cmds.split(";"):
            qsd_cmd += cmd

        # QSD images
        qsd_imgs = self.qsd_params.get("qsd_images", "").split()

        for img in qsd_imgs:
            params = self.qsd_params.object_params(img)
            img_info = self._fulfil_image_props(img, params)
            qsd_cmd += " --blockdev '%s'" % json.dumps(img_info["protocol"])
            qsd_cmd += " --blockdev '%s'" % json.dumps(img_info["format"])
            if img_info["filter"]["driver"]:
                qsd_cmd += " --blockdev '%s'" % json.dumps(img_info["filter"])
            if img_info["nbd-server"]["addr"]:
                qsd_cmd += " --nbd-server '%s'" % json.dumps(img_info["nbd-server"])
            qsd_cmd += " --export '%s'" % json.dumps(img_info["export"])

        # QSD daemonize

        if params.get("qsd_daemonize", "no") == "yes":
            if self.check_capability(Flags.DAEMONIZE):
                LOG_JOB.info("Skip --daemonize")
                qsd_cmd += " --daemonize"
                self.daemonize = True
            else:
                LOG_JOB.info("Ignore option --daemonize")

        # QSD pidfile
        if params.get("qsd_enable_pidfile", "yes") == "yes":
            if self.check_capability(Flags.PIDFILE):
                self.pidfile = "%s/%s.pid" % (self.basedir, self.name)
                qsd_cmd += " --pidfile %s" % self.pidfile
            else:
                LOG_JOB.info("Ignore option --pidfile ")

        LOG_JOB.info(qsd_cmd.replace(" --", " \\\n --"))
        self.set_param("cmd", qsd_cmd)

        # run QSD
        if self.daemonize:
            LOG_JOB.info("Run QSD on daemonize mode ")
            qsd = subprocess.Popen(qsd_cmd, shell=True)
            qsd.wait()
            if qsd.returncode:
                raise QsdError("Failed run QSD daemonize: %d" % qsd.returncode)
        else:
            super(QsdDaemonDev, self).start_daemon()
            if not self.is_daemon_alive():
                output = self.daemon_process.get_output()
                self.close_daemon_process()
                raise QsdError("Failed to run QSD daemon: %s" % output)
            LOG_JOB.info(
                "Created QSD daemon process with parent PID %d.",
                self.daemon_process.get_pid(),
            )

        pid = process.system_output(get_pid_cmd, shell=True).decode()

        if not pid:
            LOG_JOB.info("Can not Find running QSD %s ", self.name)

        if self.pidfile:
            file_pid = process.system_output(
                "cat %s" % self.pidfile, shell=True
            ).decode()
            if file_pid != pid:
                raise QsdError("Find mismatch pid: %s %s" % (pid, file_pid))

        self.pid = pid

        monitor = qemu_monitor.QMPMonitor(self, self.name, self.qsd_params)
        monitor.info_block()
        self.monitor = monitor

    def is_daemon_alive(self):
        if self.daemonize:
            check_pid_cmd = "ps -q %s" % self.pid
            if self.pid:
                return (
                    process.system(check_pid_cmd, shell=True, ignore_status=True) == 0
                )
            return False

        return super(QsdDaemonDev, self).is_daemon_alive()

    def _destroy(self):
        # Is it already dead?
        if not self.is_daemon_alive():
            LOG_JOB.info("dead")
            return

        pid = self.get_pid()
        LOG_JOB.debug("Destroying QSD %s (PID %s)", self.name, pid)

        if self.monitor:
            # Try to finish process with a monitor command
            LOG_JOB.debug("Ending VM %s process (monitor)", self.name)
            try:
                self.monitor.quit()
            except Exception as e:
                LOG_JOB.warning(e)
                if not self.is_daemon_alive():
                    LOG_JOB.warning(
                        "QSD %s down during try to kill it " "by monitor", self.name
                    )
                    return
            else:
                # Wait for the QSD to be really dead
                if utils_misc.wait_for(lambda: not self.is_daemon_alive(), timeout=10):
                    LOG_JOB.debug("QSD %s down (monitor)", self.name)
                    return
                else:
                    LOG_JOB.debug("QSD %s failed to go down (monitor)", self.name)

        LOG_JOB.debug("Killing QSD %s process (killing PID %s)", self.name, pid)
        try:
            LOG_JOB.debug("Ready to terminate qsd:%s", pid)
            utils_misc.kill_process_tree(int(pid), signal.SIGTERM, timeout=60)
            if self.is_daemon_alive():
                LOG_JOB.debug("Ready to kill qsd:%s", pid)
                utils_misc.kill_process_tree(int(pid), signal.SIGKILL, timeout=60)
            LOG_JOB.debug("VM %s down (process killed)", self.name)
        except RuntimeError:
            # If all else fails, we've got a zombie...
            LOG_JOB.error("VM %s (PID %s) is a zombie!", self.name, pid)

    def stop_daemon(self):
        try:
            self._destroy()
            super(QsdDaemonDev, self).stop_daemon()
        finally:
            self._remove_images()

    def check_capability(self, flag):
        return flag in self.caps

    def __eq__(self, other):
        if super(QsdDaemonDev, self).__eq__(other):
            return self.sock_path == other.sock_path
        return False
