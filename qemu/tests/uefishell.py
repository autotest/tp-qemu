import os
import re
import time
import logging

from avocado.utils import process

from virttest import storage
from virttest import data_dir
from virttest import utils_misc
from virttest import env_process


class UEFIShellTest(object):
    """
    Provide basic functions for uefishell test. To use UefiShell.iso
    which is provided by ovmf package. Boot your VM with this as
    the CD-ROM image and it should boot into the UEFI shell.
    """

    def __init__(self, test, params, env):
        """
        Init the default values for UEFIShell object
        :param test: Kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        self.test = test
        self.params = params
        self.env = env
        self.session = None

    def setup(self, under_fs0):
        """
        Pre-process for uefishell environment, launch vm from the
        UefiShell.iso, and setup a serial session for uefishell

        :param under_fs0: most uefi command executed under fs0:\
        """
        params = self.params
        self.var_copy()
        for cdrom in params.objects("cdroms"):
            boot_index = params.get("boot_index_%s" % cdrom)
            if boot_index is not None:
                params["boot_index_%s" % cdrom] = int(boot_index) + 1
        for image in params.objects("images"):
            params["image_boot_%s" % image] = "no"
        params["cdroms"] = "%s %s" % ("uefishell", params["cdroms"])
        params["cdrom_uefishell"] = self.copy_uefishell()
        params["bootindex_uefishell"] = "0"
        if params.get("secureboot_pk_kek"):
            params["secureboot_pk_kek"] %= self.copy_secureboot_pk_kek(
                    params["pk_kek_filename"])
            params["extra_params"] %= params["secureboot_pk_kek"]
        params["start_vm"] = "yes"
        params["shell_prompt"] = r"(Shell|FS\d:\\.*)>"
        params["shell_linesep"] = r"\r\n"
        env_process.process(self.test, params, self.env,
                            env_process.preprocess_image,
                            env_process.preprocess_vm)
        vm = self.env.get_vm(params["main_vm"])
        self.session = vm.wait_for_serial_login()
        if under_fs0 == "yes":
            self.send_command("fs0:")

    def copy_uefishell(self):
        """
        Copy uefishell.iso
        :return uefishell.iso path
        """
        ovmf_path = self.params["ovmf_path"]
        uefishell_filename = "UefiShell.iso"
        uefishell_dst_path = "images/%s" % uefishell_filename
        uefishell_src_path = utils_misc.get_path(
            ovmf_path, uefishell_filename)
        uefishell_dst_path = utils_misc.get_path(
            data_dir.get_data_dir(), uefishell_dst_path)
        if not os.path.exists(uefishell_dst_path):
            cp_command = "cp -f %s %s" % (
                uefishell_src_path, uefishell_dst_path)
            process.system(cp_command)
        return uefishell_dst_path

    def copy_secureboot_pk_kek(self, pk_kek_filename):
        """
        Copy SecureBootPkKek1.oemstr
        :return SecureBootPkKek1.oemstr path
        """
        pk_kek_filepath = data_dir.get_deps_dir("edk2")
        pk_kek_src_path = utils_misc.get_path(pk_kek_filepath,
                                              pk_kek_filename)
        pk_kek_dst_path = "images/%s" % pk_kek_filename
        pk_kek_dst_path = utils_misc.get_path(data_dir.get_data_dir(),
                                              pk_kek_dst_path)
        cp_command = "cp -f %s %s" % (pk_kek_src_path, pk_kek_dst_path)
        process.system(cp_command)
        return pk_kek_dst_path

    def var_copy(self):
        """
        Copy a new VAR file for a cleaner environment to test,
        since the operations inside uefishell will be recorded
        into VAR file and may affact later test cases.
        """
        source_var_path = "/usr/share/OVMF/OVMF_VARS.fd"
        path = storage.get_image_filename_filesytem(
            self.params, data_dir.get_data_dir())
        vars_path = "%s.fd" % path
        if os.path.exists(source_var_path):
            logging.debug("Use new var file, copied from %s", source_var_path)
            cmd = "cp -f %s %s" % (source_var_path, vars_path)
            process.system(cmd)
        else:
            self.test.cancel("fd source file %s does not exist." % source_var_path)

    def send_command(self, command, check_result=False, interval=0.5):
        """
        Send a command line to uefi shell, and check the output
        if 'check_result' exists, and fail the case if the output
        does not meet the expectation

        :param command: the command string being executed
        :param check_result: the pattern to validate output
        """
        logging.info("Send uefishell command: %s" % command)
        output = self.session.cmd_output_safe(command)
        time.sleep(interval)
        #Judge if cmd is run successfully via environment variable 'lasterror'
        last_error = self.params["last_error"]
        env_var = self.session.cmd_output_safe("set")
        if not re.search(last_error, env_var):
            self.test.fail("Following errors appear %s when running command %s"
                           % (output, command))
        if check_result:
            for result in check_result.split(", "):
                if not re.search(result, output):
                    self.test.fail("The command result is: %s, which does not"
                                   " match the expectation: %s" % (output, result))

    def post_test(self):
        """
        To execute post test if have, e.g. guest installation. And
        post test step should be defined within a function of this
        class UEFIShell
        """
        post_tests = self.params.get("post_tests", "")
        for test in post_tests.split():
            if hasattr(self, test):
                func = getattr(self, test)
                func()

    def clean(self):
        """
        To clean the test environment, including restore VAR file
        and close the session
        """
        if self.session:
            self.session.close()


def run(test, params, env):
    """
    Uefishell test:
    1. Boot up guest from uefishell.iso, to enter uefishell
    2. Execute uefishell command
    3. Justify if the response of the commmand correct
    4. Execute post action out of uefishell
    5. Clean test environment

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    uefishell_test = UEFIShellTest(test, params, env)
    time_interval = float(params["time_interval"])
    under_fs0 = params.get("under_fs0", "yes")
    uefishell_test.setup(under_fs0)
    test_scenarios = params["test_scenarios"]
    for scenario in test_scenarios.split():
        command = params["command_%s" % scenario]
        check_result = params.get("check_result_%s" % scenario)
        uefishell_test.send_command(command, check_result, time_interval)
    uefishell_test.post_test()
    uefishell_test.clean()
