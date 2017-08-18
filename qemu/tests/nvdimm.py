import os
import logging

from autotest.client.shared import error
from avocado.utils import process

from virttest import env_process


class NvdimmTest(object):
    """
    Class for NVDIMM test
    """

    def __init__(self, params, env):
        """
        Init the default values of NvdimmTest object.

        :param params: A dict containing VM preprocessing parameters.
        :param env: The environment (a dict-like object).
        """
        self.session = None
        self.params = params
        self.env = env

    def run_guest_cmd(self, cmd, check_status=True):
        """
        Run command in guest

        :param cmd: A command needed to run
        :param check_status: If true, check the status after running the cmd
        :return: The output after running the cmd
        """
        status, output = self.session.cmd_status_output(cmd)
        if check_status and status != 0:
            raise error.TestFail("Execute command '%s' failed, output: %s")
        return output.strip()

    def verify_nvdimm(self, vm):
        """
        verify nvdimm in monitor and guest

        :params vm: VM object
        """
        dimms_expect = set(["dimm-%s" % dev for dev in self.params.objects("mem_devs")])
        dimms_monitor = set([info["data"]["id"] for info in vm.monitor.info("memory-devices")])
        if not dimms_expect.issubset(dimms_monitor):
            invisible_dimms = dimms_expect - dimms_monitor
            raise error.TestFail("%s dimms are invisible in monitor" % invisible_dimms)
        check_cmd = "test -b %s" % self.params.get("pmem", "/dev/pmem0")
        self.run_guest_cmd(check_cmd)

    def format_nvdimm(self):
        """
        Format nvdimm device in guest
        """
        format_cmd = self.params["format_command"]
        self.run_guest_cmd(format_cmd)

    def mount_nvdimm(self, format_device="yes"):
        """
        Mount nvdimm device in guest

        :param format_device: A string to specify if format the device or not
        """
        if format_device == "yes":
            self.format_nvdimm()
        mount_cmd = self.params["mount_command"]
        self.run_guest_cmd(mount_cmd)

    def umount_nvdimm(self):
        """
        Umount nvdimm device in guest.
        """
        umount_cmd = "umount %s" % self.params["pmem"]
        self.run_guest_cmd(umount_cmd)

    def md5_hash(self, file):
        """
        Get the md5 value of the file

        :param file: A file with fullpath
        :return: The md5 value of the file
        """
        cmd = "md5sum %s" % file
        return self.run_guest_cmd(cmd)


@error.context_aware
def run(test, params, env):
    """
    Run nvdimm cases:
    1) Boot guest with nvdimm device backed by a host file
    2) Login to the guest
    3) Check nvdimm in monitor and guest
    4) Format nvdimm device in guest
    5) Mount nvdimm device in guest
    6) Create a file in the mount point in guest
    7) Check the md5 value of the file
    8) Umount the nvdimm device and check calltrace in guest
    9) Reboot the guest
    10) Remount nvdimm device in guest
    11) Check if the md5 value of the nv_file changes

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    if params["start_vm"] == "no":
        error.context("Check nvdimm backend in host", logging.info)
        try:
            process.system("grep 'memmap=' /proc/cmdline")
        except process.CmdError:
            raise error.TestError("Please add kernel param 'memmap' before start test.")
        if not os.path.exists(params["nv_backend"]):
            raise error.TestError("Check nv_backend in host failed!")
        params["start_vm"] = "yes"
        vm_name = params['main_vm']
        env_process.preprocess_vm(test, params, env, vm_name)

    nvdimm_test = NvdimmTest(params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    try:
        error.context("Login to the guest", logging.info)
        login_timeout = int(params.get("login_timeout", 360))
        nvdimm_test.session = vm.wait_for_login(timeout=login_timeout)
        error.context("Verify nvdimm in monitor and guest", logging.info)
        nvdimm_test.verify_nvdimm(vm)
        error.context("Format and mount nvdimm in guest", logging.info)
        nvdimm_test.mount_nvdimm()
        nv_file = params.get("nv_file", "/mnt/nv")
        error.context("Create a file in nvdimm mount dir in guest, and get "
                      "original md5 of the file", logging.info)
        dd_cmd = "dd if=/dev/urandom of=%s bs=1K count=200" % nv_file
        nvdimm_test.run_guest_cmd(dd_cmd)
        orig_md5 = nvdimm_test.md5_hash(nv_file)
        nvdimm_test.umount_nvdimm()
        nvdimm_test.session = vm.reboot()
        error.context("Verify nvdimm after reboot", logging.info)
        nvdimm_test.verify_nvdimm(vm)
        nvdimm_test.mount_nvdimm(format_device="no")
        new_md5 = nvdimm_test.md5_hash(nv_file)
        error.context("Compare current md5 to original md5", logging.info)
        if new_md5 != orig_md5:
            raise error.TestFail("'%s' changed. The original md5 is '%s',"
                                 " current md5 is '%s'"
                                 % (nv_file, orig_md5, new_md5))
        nvdimm_test.umount_nvdimm()
        error.context("Check if error and calltrace in guest", logging.info)
        vm.verify_kernel_crash()

    finally:
        if nvdimm_test.session:
            nvdimm_test.session.close()
        vm.destroy()
