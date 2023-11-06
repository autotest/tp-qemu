"""
Module for VDPA block device interfaces.
"""
import logging
import time

from avocado.utils import process
from virttest.vdpa_blk import get_image_filename

from virttest.utils_kernel_module import KernelModuleHandler

LOG = logging.getLogger('avocado.test')


class VDPABlkSimulatorError(Exception):
    """ General VDPA BLK error"""
    pass


class VDPABlkSimulatorTest(object):

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

    def add_vdpa_blk_dev(self, name):
        """
        Add vDPA blk device
        :param name: device name
        :return : host device name ,eg. vda,vdb
        """
        raise VDPABlkSimulatorError("Please implement add_vdpa_blk_dev")

    def remove_vdpa_blk_dev(self, name):
        """
        Remove vDPA blk device
        :param name: device name
        """
        cmd = "vdpa dev del %s" % name
        process.run(cmd, shell=True, ignore_status=True)
        cmd = "vdpa dev list -jp %s" % name
        cmd_result = process.run(cmd, shell=True, ignore_status=True)
        if cmd_result.exit_status == 0:
            raise VDPABlkSimulatorError("The vdpa block %s still exist" % name)

    def setup(self, opts={}):
        """
        Setup vDPA BLK Simulator environment
        Example: setup({"vdpa-sim-blk": "shared_backend=1"})
        """
        LOG.debug("Loading vDPA Kernel modules..%s", self._modules)
        self.load_modules(opts)

    def cleanup(self):
        """
        Cleanup vDPA BLK Simulator environment
        """
        self.unload_modules()
        LOG.info("vDPA Simulator environment recover successfully.")


class VhostVdpaSimulatorTest(VDPABlkSimulatorTest):
    def __init__(self):
        super(VhostVdpaSimulatorTest, self).__init__()
        self._modules = ['vhost-vdpa', 'vdpa-sim-blk']

    def add_vdpa_blk_dev(self, name):
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
            raise VDPABlkSimulatorError(
                "vdpa dev add %s failed:%s" % (name, str(e)))
        return dev


class VirtioVdpaSimulatorTest(VDPABlkSimulatorTest):
    def __init__(self):
        super(VirtioVdpaSimulatorTest, self).__init__()
        self._modules = ['virtio-vdpa', 'vdpa-sim-blk']

    def add_vdpa_blk_dev(self, name):
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
            raise VDPABlkSimulatorError("vdpa dev add %s failed" % name)
        return host_dev[0]
