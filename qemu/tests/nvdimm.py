import logging

from autotest.client.shared import error


class NvdimmTest(object):
    """
    Class for NVDIMM test
    """
    def __init__(self, test, params, env):
        self.session = {}
        self.test = test
        self.params = params
        self.env = env

    def check_nvdimm(self):
        """
        Check nvdimm in guest
        """
        pmem = self.params.get('pmem', '/dev/pmem0')
        check_cmd = "ls " + pmem
        status, output = self.session.cmd_status_output(check_cmd, timeout=10)
        if status != 0:
            raise error.TestFail("check %s in guest failed: %s"
                                 % (pmem, output))

    def format_nvdimm(self):
        """
        Format nvdimm device in guest
        """
        format_cmd = self.params.get('format_command')
        status, output = self.session.cmd_status_output(format_cmd, timeout=20)
        if status != 0:
            raise error.TestFail("Format command failed: %s" % output)

    def mount_nvdimm(self, format_device="yes"):
        """
        Mount nvdimm device in guest
        """
        self.check_nvdimm()
        if format_device == "yes":
            self.format_nvdimm()
        mount_cmd = self.params.get('mount_command')
        status, output = self.session.cmd_status_output(mount_cmd, timeout=10)
        if status != 0:
            raise error.TestFail("Mount nvdimm device failed: %s" % output)


class NvdimmBasicTest(NvdimmTest):

    def start_test(self):
        vm = self.env.get_vm(self.params["main_vm"])
        vm.verify_alive()

        error.context("Login to the guest", logging.info)
        login_timeout = int(self.params.get("login_timeout", 360))
        self.session = vm.wait_for_login(timeout=login_timeout)
        cmd_timeout = int(self.params.get("cmd_timeout", 360))

        if self.params.get("os_type") == 'linux':
            self.mount_nvdimm()
            nv_file = self.params.get('nv_file', "/mnt/nv")
            dd_cmd = "dd if=/dev/urandom of=%s bs=1K count=200" % nv_file
            status, output = self.session.cmd_status_output(dd_cmd,
                                                            timeout=cmd_timeout)
            if status != 0:
                raise error.TestFail("%s failed: %s" % (dd_cmd, output))

            md5_cmd = "md5sum %s" % nv_file
            status, output = self.session.cmd_status_output(md5_cmd,
                                                            timeout=cmd_timeout)
            if status != 0:
                raise error.TestFail("Failed to get md5: %s" % output)
            orig_md5 = output
            mount_dir = self.params.get("mount_dir", "/mnt")
            umount_cmd = "umount %s" % mount_dir
            status, output = self.session.cmd_status_output(umount_cmd,
                                                            timeout=cmd_timeout)
            self.session = vm.reboot(session=self.session)
            self.mount_nvdimm(format_device="no")
            status, output = self.session.cmd_status_output(md5_cmd,
                                                            timeout=cmd_timeout)
            if status != 0:
                raise error.TestFail("Failed to get md5: %s" % output)
            new_md5 = output
            logging.info("compare md5")
            if new_md5 != orig_md5:
                raise error.TestFail("'%s' changed. The original md5 is '%s',"
                                     " current md5 is '%s'"
                                     % (nv_file, orig_md5, new_md5))

        self.session.close()


@error.context_aware
def run(test, params, env):
    """
    Run nvdimm cases:
    1) Boot guest with nvdimm device backed by a host file
    2) Login to the guest
    3) Check nvdimm in guest
    4) Format nvdimm device in guest
    5) Mount nvdimm device in guest
    6) Create a file in the mount point in guest
    7) Check the md5 value of the file
    8) Umount the nvdimm device in guest
    9) Reboot the guest
    10) Remount nvdimm device in guest
    11) Check if the md5 value of the nv_file changes

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    nvdimm_test = NvdimmBasicTest(test, params, env)
    nvdimm_test.start_test()
