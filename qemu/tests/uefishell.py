import logging
import os
import random
import re
import time

from avocado.utils import process
from virttest import data_dir, env_process, utils_misc, utils_net, utils_qemu

from provider.cpu_utils import check_cpu_flags

LOG_JOB = logging.getLogger("avocado.test")


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
        self.vm = None

    def set_cpu_model(self, cpu_model_list):
        """
        set cpu model by the given cpu model list

        :param cpu_model_list: a list of cpu model
        """
        qemu_binary = "/usr/libexec/qemu-kvm"
        cpu_list = utils_qemu.get_supported_devices_list(qemu_binary, "CPU")
        cpu_list = list(map(lambda x: x.split("-")[0], cpu_list))
        cpu_model_list = list(filter(lambda x: x in cpu_list, cpu_model_list))
        self.params["cpu_model"] = random.choice(cpu_model_list)

    def check_host_cpu_flags(self):
        """
        check if the host supports the cpu flags
        """
        check_host_flags = self.params.get_boolean("check_host_flags")
        if check_host_flags:
            check_cpu_flags(self.params, self.params["flags"], self.test)

    def check_message_in_serial_log(self, msg):
        """
        check the given message in serial log

        :param msg: the message to be checked in serial log
        """
        serial_output = self.vm.serial_console.get_output()
        if not re.search(msg, serial_output, re.S):
            self.test.fail("Can't find 'msg' in serial log.")

    def check_message_in_edk2_log(self, msg):
        """
        check the given message in edk2 log

        :param msg: the message to be checked in edk2 log
        """
        logs = self.vm.logsessions["seabios"].get_output()
        if not re.search(msg, logs, re.S):
            self.test.fail("Can't find 'msg' in edk2 log.")

    def setup(self, under_fs0):
        """
        Pre-process for uefishell environment, launch vm from the
        UefiShell.iso, and setup a serial session for uefishell

        :param under_fs0: most uefi command executed under fs0:\
        """
        if not self.params.get_boolean("auto_cpu_model"):
            self.set_cpu_model(self.params.get_list("cpu_model_list"))
        self.check_host_cpu_flags()
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
                params["pk_kek_filename"]
            )
            params["extra_params"] %= params["secureboot_pk_kek"]
        params["start_vm"] = "yes"
        params["shell_prompt"] = r"(Shell|FS\d:\\.*)>"
        params["shell_linesep"] = r"\r\n"
        env_process.process(
            self.test,
            params,
            self.env,
            env_process.preprocess_image,
            env_process.preprocess_vm,
        )
        self.vm = self.env.get_vm(params["main_vm"])
        self.session = self.vm.wait_for_serial_login()
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
        uefishell_src_path = utils_misc.get_path(ovmf_path, uefishell_filename)
        uefishell_dst_path = utils_misc.get_path(
            data_dir.get_data_dir(), uefishell_dst_path
        )
        if not os.path.exists(uefishell_dst_path):
            cp_command = "cp -f %s %s" % (uefishell_src_path, uefishell_dst_path)
            process.system(cp_command)
        return uefishell_dst_path

    def copy_secureboot_pk_kek(self, pk_kek_filename):
        """
        Copy SecureBootPkKek1.oemstr
        :return SecureBootPkKek1.oemstr path
        """
        pk_kek_filepath = data_dir.get_deps_dir("edk2")
        pk_kek_src_path = utils_misc.get_path(pk_kek_filepath, pk_kek_filename)
        pk_kek_dst_path = "images/%s" % pk_kek_filename
        pk_kek_dst_path = utils_misc.get_path(data_dir.get_data_dir(), pk_kek_dst_path)
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
        LOG_JOB.info("Send uefishell command: %s", command)
        output = self.session.cmd_output(command)
        time.sleep(interval)
        # Judge if cmd is run successfully via environment variable 'lasterror'
        last_error = self.params["last_error"]
        env_var = self.session.cmd_output_safe("set")
        if not re.search(last_error, env_var, re.S):
            self.test.fail(
                "Following errors appear %s when running command %s" % (output, command)
            )
        if check_result:
            value = []
            for result in check_result.split(", "):
                if not re.findall(result, output, re.S):
                    self.test.fail(
                        "The command result is: %s, which does not"
                        " match the expectation: %s" % (output, result)
                    )
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

    def form_ping_args():
        """
        get target ip address ver4
        """
        return utils_net.get_host_ip_address(params)

    def form_ping6_args():
        """
        get source ip address and target ip address ver6
        """
        src_ipv6 = uefishell_test.send_command(
            params["command_show6"], params["check_result_show6"], time_interval
        )
        target_ipv6 = utils_net.get_host_ip_address(params, "ipv6", True).split("%")[0]
        return " ".join([src_ipv6[0], target_ipv6])

    def handle_memory_map(output):
        """
        search all RT_Code lines from output, each line ends
        with 800000000000000F;
        search two adjacent RT_Code lines, the result should be None
        """
        attribute_values = re.findall(params["rt_code_lines"], output[0], re.M)
        for value in attribute_values:
            if params["attribute_value"] != value:
                test.fail(
                    "The last column should be '%s' for all "
                    "RT_Code entries. The actual value is '%s'"
                    % (params["attribute_value"], value)
                )
        if re.search(params["adjacent_rt_code_lines"], output[0], re.M):
            test.fail(
                "Found two adjacent RT_Code lines in command output. "
                "The range of 'RT_Code' should be covered by just one"
                " entry. The command output is %s" % output[0]
            )

    def handle_smbiosview(output):
        """
        check the following 3 values from output
        smbios version: if smbios-entry-point-type=32, the version is 2.*
                        e.g. 2.8
                        if smbios-entry-point-type=64, the version is 3.*
                        e.g. 3.0
        bios version: show the build version
                      e.g. edk2-20221207gitfff6d81270b5-1.el9
        bios release date: show the release date, e.g. 12/07/2022
                           it should be equal to the date string in
                           bios version
        """
        smbios_version = re.findall(params["smbios_version"], output[0], re.S)
        if not smbios_version:
            test.fail(
                "Failed to find smbios version. " "The command output is %s" % output[0]
            )
        bios_version = re.findall(params["bios_version"], output[0], re.S)
        if not bios_version:
            test.fail(
                "Failed to find bios version. " "The command output is %s" % output[0]
            )
        bios_release_date = re.search(params["bios_release_date"], output[0], re.S)
        if not bios_release_date:
            test.fail(
                "Failed to find bios_release_date. "
                "The command output is %s" % output[0]
            )
        date_year = bios_version[0][:4]
        date_month = bios_version[0][4:6]
        date_day = bios_version[0][6:]
        if (
            date_year != bios_release_date.group("year")
            or date_month != bios_release_date.group("month")
            or date_day != bios_release_date.group("day")
        ):
            test.fail(
                "The bios release dates are not equal between "
                "bios_version and bios_release_date. The date from "
                "bios_version is %s, the date from bios_release_date "
                "is %s." % (bios_version[0], bios_release_date[0])
            )

    uefishell_test = UEFIShellTest(test, params, env)
    time_interval = float(params["time_interval"])
    under_fs0 = params.get("under_fs0", "yes")
    uefishell_test.setup(under_fs0)
    if params.get("check_message"):
        uefishell_test.check_message_in_serial_log(params["check_message"])
        uefishell_test.check_message_in_edk2_log(params["check_message"])
    test_scenarios = params["test_scenarios"]
    for scenario in test_scenarios.split():
        command = params["command_%s" % scenario]
        if params.get("command_%s_%s" % (scenario, "args")):
            func_name = params["command_%s_%s" % (scenario, "args")]
            command += eval(func_name)
        check_result = params.get("check_result_%s" % scenario)
        output = uefishell_test.send_command(command, check_result, time_interval)
        if params.get("%s_output_handler" % scenario):
            func_name = params["%s_output_handler" % scenario]
            eval(func_name)(output)
    uefishell_test.post_test()
    uefishell_test.clean()
