"""
Module for VDPA block/net device interfaces.
"""

import glob
import logging
import os
import time

from aexpect.utils import wait
from avocado.utils import process
from virttest.utils_kernel_module import KernelModuleHandler
from virttest.vdpa_blk import get_image_filename

LOG = logging.getLogger("avocado.test")


class VDPABlkNetSimulatorError(Exception):
    """General VDPA BLK/Net error"""

    pass


class VDPABlkNetSimulatorTest(object):
    def __init__(self):
        self._modules = []

    def __del__(self):
        self.cleanup()

    def load_modules(self, opts={}):
        """
        Load modules
        """
        self.unload_modules()

        for module_name in self._modules:
            opt = ""
            if module_name in opts.keys():
                opt = opts[module_name]
            KernelModuleHandler(module_name).reload_module(True, opt)

    def unload_modules(self):
        """
        Unload modules
        """
        for module_name in self._modules:
            KernelModuleHandler(module_name).unload_module()

    def add_dev(self, name):
        """
        Add vDPA device
        :param name: device name
        :return : host device name ,eg. vda,vdb
        """
        raise VDPABlkNetSimulatorError("Please implement add_dev")

    def remove_dev(self, name):
        """
        Remove vDPA device
        :param name: device name
        """
        cmd = "vdpa dev del %s" % name
        process.run(cmd, shell=True, ignore_status=True)
        cmd = "vdpa dev list -jp %s" % name
        cmd_result = process.run(cmd, shell=True, ignore_status=True)
        if cmd_result.exit_status == 0:
            raise VDPABlkNetSimulatorError("The vdpa device %s still exist" % name)

    def setup(self, opts={}):
        """
        Setup vDPA BLK/Net Simulator environment
        Example: setup({"vdpa-sim-blk": "shared_backend=1"})
        """
        LOG.debug("Loading vDPA Kernel modules..%s", self._modules)
        self.load_modules(opts)

    def cleanup(self):
        """
        Cleanup vDPA BLK/Net Simulator environment
        """
        self.unload_modules()
        LOG.info("vDPA Simulator environment recover successfully.")


class VhostVdpaBlkSimulatorTest(VDPABlkNetSimulatorTest):
    def __init__(self):
        super(VhostVdpaBlkSimulatorTest, self).__init__()
        self._modules = ["vhost-vdpa", "vdpa-sim-blk"]

    def add_dev(self, name):
        """
        Add vDPA blk device
        :param name: device name
        :return : host device name ,eg. /dev/vhost-vdpa-X
        """

        cmd = "vdpa dev add mgmtdev vdpasim_blk name %s" % name
        process.run(cmd, shell=True)
        cmd = "vdpa dev list -jp %s" % name
        process.run(cmd, shell=True)

        time.sleep(2)
        try:
            dev = get_image_filename(name).replace("vdpa://", "")
        except Exception as e:
            raise VDPABlkNetSimulatorError("vdpa dev add %s failed:%s" % (name, str(e)))
        return dev


class VirtioVdpaBlkSimulatorTest(VDPABlkNetSimulatorTest):
    def __init__(self):
        super(VirtioVdpaBlkSimulatorTest, self).__init__()
        self._modules = ["virtio-vdpa", "vdpa-sim-blk"]

    def add_dev(self, name):
        """
        Add vDPA blk device
        :param name: device name
        :return : host device name ,eg. vda,vdb
        """

        disk_cmd = "lsblk -nd -o name "
        disks = process.system_output(disk_cmd, shell=True).decode().split()
        dev_before = set(disks)
        cmd = "vdpa dev add mgmtdev vdpasim_blk name %s" % name
        process.run(cmd, shell=True)
        cmd = "vdpa dev list -jp %s" % name
        process.run(cmd, shell=True)
        time.sleep(2)
        disks = process.system_output(disk_cmd, shell=True).decode().split()
        dev_after = set(disks)
        host_dev = list(dev_after - dev_before)
        if not host_dev:
            raise VDPABlkNetSimulatorError("vdpa dev add %s failed" % name)
        return host_dev[0]


class VhostVdpaNetSimulatorTest(VDPABlkNetSimulatorTest):
    def __init__(self):
        super(VhostVdpaNetSimulatorTest, self).__init__()
        self._modules = ["vhost-vdpa", "vdpa-sim", "vdpa-sim-net"]

    def add_dev(self, name, mac):
        """
        Add vDPA net device
        :param name: device name
        :param mac: MAC address
        :return : host device name ,eg. /dev/vhost-vdpa-X
        """

        cmd = "vdpa dev add name %s mgmtdev vdpasim_net mac %s" % (name, mac)
        process.run(cmd, shell=True)
        cmd = "vdpa dev list -jp %s" % name
        process.run(cmd, shell=True)

        time.sleep(2)
        try:
            dev = get_image_filename(name).replace("vdpa://", "")
        except Exception as e:
            raise VDPABlkNetSimulatorError("vdpa dev add %s failed:%s" % (name, str(e)))
        return dev


class VirtioVdpaNetSimulatorTest(VDPABlkNetSimulatorTest):
    def __init__(self):
        super(VirtioVdpaNetSimulatorTest, self).__init__()
        self._modules = ["vdpa", "virtio-vdpa", "vdpa_sim", "vdpa-sim-net"]

    def add_dev(self, name, mac):
        """
        Add vDPA net device
        :param name: device name
        :param mac: MAC address
        :return : host device name ,eg. eth0
        """

        cmd = "vdpa dev add name %s mgmtdev vdpasim_net mac %s" % (name, mac)
        process.run(cmd, shell=True)
        cmd = "vdpa dev list -jp %s" % name
        process.run(cmd, shell=True)
        virtio_dir = "/sys/bus/vdpa/devices/{}/virtio*/net/*".format(name)
        virtio_path = wait.wait_for(lambda: glob.glob(virtio_dir), 2)
        if virtio_path:
            return os.path.basename(virtio_path[0])
        else:
            raise VDPABlkNetSimulatorError("vdpa dev add %s failed:%s" % name)
