import logging
import os
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_package
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


class NvdimmTest(object):
    """
    Class for NVDIMM test
    """

    def __init__(self, test, params, env):
        """
        Init the default values of NvdimmTest object.

        :param params: A dict containing VM preprocessing parameters.
        :param env: The environment (a dict-like object).
        """
        self.session = None
        self.test = test
        self.params = params
        self.env = env

    def run_guest_cmd(self, cmd, check_status=True, timeout=240):
        """
        Run command in guest

        :param cmd: A command needed to run
        :param check_status: If true, check the status after running the cmd
        :return: The output after running the cmd
        """
        status, output = self.session.cmd_status_output(cmd, timeout=timeout)
        if check_status and status != 0:
            self.test.fail("Execute command '%s' failed, output: %s" % (cmd, output))
        return output.strip()

    def verify_nvdimm(self, vm, mems):
        """
        verify nvdimm in monitor and guest

        :params vm: VM object
        :params mems: memory objects
        """
        dimms_expect = set("dimm-%s" % mem for mem in mems)
        LOG_JOB.info("Check if dimm %s in memory-devices", dimms_expect)
        dimms_monitor = set(
            [info["data"]["id"] for info in vm.monitor.info("memory-devices")]
        )
        if not dimms_expect.issubset(dimms_monitor):
            invisible_dimms = dimms_expect - dimms_monitor
            self.test.fail("%s dimms are invisible in monitor" % invisible_dimms)
        check_cmd = "test -b %s" % self.params.get("dev_path", "/dev/pmem0")
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
        umount_cmd = "umount %s" % self.params["dev_path"]
        self.run_guest_cmd(umount_cmd)

    def md5_hash(self, file):
        """
        Get the md5 value of the file

        :param file: A file with fullpath
        :return: The md5 value of the file
        """
        cmd = "md5sum %s" % file
        return self.run_guest_cmd(cmd)


@error_context.context_aware
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
        error_context.context("Check nvdimm backend in host", test.log.info)
        try:
            process.system("grep 'memmap=' /proc/cmdline")
        except process.CmdError:
            test.error("Please add kernel param 'memmap' before start test.")
        if params.get("nvdimm_dax") == "yes":
            try:
                process.system(params["ndctl_install_cmd"], shell=True)
            except process.CmdError:
                test.error("ndctl is not available in host!")
            ndctl_ver = process.system_output("ndctl -v", shell=True)
            if float(ndctl_ver) < 56:
                test.cancel(
                    "ndctl version should be equal or greater than 56!"
                    "Current ndctl version is %s." % ndctl_ver
                )
            try:
                process.system(params["create_dax_cmd"], shell=True)
            except process.CmdError:
                test.error("Creating dax failed!")
        if not os.path.exists(params["nv_backend"]):
            test.fail("Check nv_backend in host failed!")
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)

    nvdimm_test = NvdimmTest(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    try:
        error_context.context("Login to the guest", test.log.info)
        login_timeout = int(params.get("login_timeout", 360))
        nvdimm_test.session = vm.wait_for_login(timeout=login_timeout)
        mems = params.objects("mem_devs")
        target_mems = params.objects("target_mems")
        if target_mems:
            hotplug_test = MemoryHotplugTest(test, params, env)
            for mem in target_mems:
                hotplug_test.hotplug_memory(vm, mem)
            time.sleep(10)
            mems += target_mems
        error_context.context("Verify nvdimm in monitor and guest", test.log.info)
        pkgs = params.objects("depends_pkgs")
        if not utils_package.package_install(pkgs, nvdimm_test.session):
            test.cancel("Install dependency packages failed")
        nvdimm_ns_create_cmd = params.get("nvdimm_ns_create_cmd")
        if nvdimm_ns_create_cmd:
            nvdimm_test.run_guest_cmd(nvdimm_ns_create_cmd)
        nvdimm_test.verify_nvdimm(vm, mems)
        error_context.context("Format and mount nvdimm in guest", test.log.info)
        nvdimm_test.mount_nvdimm()
        if params.get("nvml_test", "no") == "yes":
            nvdimm_test.run_guest_cmd(params["export_pmem_conf"])
            nvdimm_test.run_guest_cmd(params["get_nvml"])
            nvdimm_test.run_guest_cmd(params["compile_nvml"])
            nvdimm_test.run_guest_cmd(params["config_nvml"])
            nvdimm_test.run_guest_cmd(params["build_tests"])
            nvdimm_test.run_guest_cmd(params["run_test"], timeout=3600)
            return
        nv_file = params.get("nv_file", "/mnt/nv")
        error_context.context(
            "Create a file in nvdimm mount dir in guest, and get "
            "original md5 of the file",
            test.log.info,
        )
        dd_cmd = "dd if=/dev/urandom of=%s bs=1K count=200" % nv_file
        nvdimm_test.run_guest_cmd(dd_cmd)
        orig_md5 = nvdimm_test.md5_hash(nv_file)
        nvdimm_test.umount_nvdimm()
        nvdimm_test.session = vm.reboot()
        error_context.context("Verify nvdimm after reboot", test.log.info)
        nvdimm_test.verify_nvdimm(vm, mems)
        nvdimm_test.mount_nvdimm(format_device="no")
        new_md5 = nvdimm_test.md5_hash(nv_file)
        error_context.context("Compare current md5 to original md5", test.log.info)
        if new_md5 != orig_md5:
            test.fail(
                "'%s' changed. The original md5 is '%s', current md5 is '%s'"
                % (nv_file, orig_md5, new_md5)
            )
        nvdimm_test.umount_nvdimm()
        error_context.context("Check if error and calltrace in guest", test.log.info)
        vm.verify_kernel_crash()

    finally:
        if nvdimm_test.session:
            if params.get("nvml_dir"):
                nvdimm_test.run_guest_cmd("rm -rf %s" % params.get("nvml_dir"))
            nvdimm_test.session.close()
        vm.destroy()
        if params.get("nvdimm_dax") == "yes":
            try:
                process.system(params["del_dax_cmd"], timeout=240, shell=True)
            except process.CmdError:
                test.log.warning("Host dax configuration cannot be deleted!")
