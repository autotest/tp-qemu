import logging
import os
import shutil
import re
import time

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest import utils_misc


def boot_check(vm, info):
    """
    boot info check
    """
    logs = vm.logsessions['seabios'].get_output()
    result = re.search(info, logs, re.S)
    return result


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

    def setup(self):
        """
        Pre-process for uefishell environment, launch vm from the
        UefiShell.iso, and setup a serial session for uefishell

        :param under_fs0: most uefi command executed under fs0:\
        """
        params = self.params
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
        self.vm = self.env.get_vm(params["main_vm"])
        boot_menu_hint = params["boot_menu_hint"]
        enter_uefi_key = params["enter_uefi_key"].split(";")
        if not utils_misc.wait_for(lambda: boot_check(self.vm, boot_menu_hint),
                                   60, 1):
            self.test.fail("Could not get boot menu message")
        list(map(self.vm.send_key, enter_uefi_key))
        time.sleep(10)
        self.session = self.vm.wait_for_serial_login()

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

    def send_command(self, command, check_result=None, interval=0.5):
        """
        Send a command line to uefi shell, and check the output
        if 'check_result' exists, and fail the case if the output
        does not meet the expectation

        :param command: the command string being executed
        :param check_result: the pattern to validate output
        :param interval: time interval between commands
        :return if check_result is not None, return matched string list
        """
        logging.info("Send uefishell command: %s", command)
        output = self.session.cmd_output_safe(command)
        time.sleep(interval)
        # Judge if cmd is run successfully via environment variable 'lasterror'
        last_error = self.params["last_error"]
        env_var = self.session.cmd_output_safe("set")
        if not re.search(last_error, env_var, re.S):
            self.test.fail("Following errors appear %s when running command %s"
                           % (output, command))
        if check_result:
            value = []
            for result in check_result.split(", "):
                if not re.findall(result, output, re.S):
                    self.test.fail("The command result is: %s, which does not"
                                   " match the expectation: %s"
                                   % (output, result))
                else:
                    result = re.findall(result, output, re.S)[0]
                    value.append(result)
            return value
        return [output]

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


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs support in edk2
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofsd daemons.
        3. Boot a guest on the host with uefishell.
        4. Enter uefishell and execute uefishell command

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # set fs daemon path
    fs_source = params.get('fs_source_dir')
    install_cmd = params["install_cmd"]
    base_dir = params.get('fs_source_base_dir', data_dir.get_data_dir())

    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    if os.path.exists(fs_source):
        shutil.rmtree(fs_source, ignore_errors=True)
    logging.info("Create filesystem source %s.", fs_source)
    os.makedirs(fs_source)
    process.run(install_cmd % fs_source, shell=True)

    sock_path = os.path.join(data_dir.get_tmp_dir(),
                             '-'.join(('avocado-vt-vm1', 'viofs',
                                       'virtiofsd.sock')))
    params['fs_source_user_sock_path'] = sock_path

    # run daemon
    cmd_run_virtiofsd = params["cmd_run_virtiofsd"]
    cmd_run_virtiofsd = cmd_run_virtiofsd % (sock_path, fs_source)
    logging.info('Running daemon command %s.', cmd_run_virtiofsd)
    process.SubProcess(cmd_run_virtiofsd, shell=True).start()

    params["start_vm"] = "yes"
    uefishell_test = UEFIShellTest(test, params, env)
    uefishell_test.setup()
    command_list = params["command_list"].split(";")
    for name in command_list:
        command = params["command_%s" % name]
        check_result = params.get("check_result_%s" % name)
        uefishell_test.send_command(command, check_result)
    uefishell_test.post_test()
    uefishell_test.clean()
