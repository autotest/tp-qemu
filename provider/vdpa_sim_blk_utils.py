"""
Module for VDPA block device interfaces.
"""
import logging
import time

from avocado.utils import process

from virttest.utils_kernel_module import KernelModuleHandler

LOG = logging.getLogger('avocado.test')


class VDPABlkSimulatorError(Exception):
    """ General VDPA BLK error"""
    pass


class VDPABlkSimulatorTest(object):

    def __init__(self):
        pass

    def __del__(self):
        self.cleanup()

    def load_modules(self):
        """
        Load modules
        """
        self.unload_modules()
        modules = ['virtio-vdpa', 'vhost-vdpa', 'vdpa-sim-blk']
        for module_name in modules:
            KernelModuleHandler(module_name).reload_module(True)

    def unload_modules(self):
        """
        Unload modules
        """
        modules = ['vdpa-sim-blk', 'vhost-vdpa', 'virtio-vdpa']
        for module_name in modules:
            KernelModuleHandler(module_name).unload_module()

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

    def setup(self):
        """
        Setup vDPA BLK Simulator environment
        """
        LOG.debug("Loading vDPA Kernel modules...")
        self.load_modules()

    def cleanup(self):
        """
        Cleanup vDPA BLK Simulator environment
        """
        self.unload_modules()
        LOG.info("vDPA Simulator environment recover successfully.")
