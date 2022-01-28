import logging
import re

from avocado.utils import process

from virttest import error_context
from virttest import env_process
from virttest import utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Verify the TPM device info inside guest and host.
    Steps:
        1. Boot guest with a emulator TPM device or pass through device.
        2. Check and verify TPM/vTPM device info inside guest.
        3. Check and verify TPM/vTPM device info in the OVMF log on host.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def search_keywords(patterns, string, flags=re.M, split_string=';'):
        logging.info(string)
        for pattern in patterns.split(split_string):
            if not re.search(r'%s' % pattern, string, flags):
                test.fail('No Found pattern "%s" from "%s".' % (pattern, string))
            if re.search(r'error', string, re.M | re.A):
                test.error('Found errors from "%s".' % string)

    cmd_get_tpm_ver = params.get('cmd_get_tpm_version')
    cmd_check_tpm_dev = params.get('cmd_check_tpm_device')
    depends_pkgs = params.get('depends_pkgs')

    if not utils_package.package_install(depends_pkgs):
        test.cancel("Please install %s on host", depends_pkgs)
    if not cmd_check_tpm_dev:
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    if cmd_check_tpm_dev:
        status, output = process.getstatusoutput(cmd_check_tpm_dev)
        if status:
            test.cancel('No found TPM device on host, output: %s' % output)
        if cmd_get_tpm_ver:
            actual_tpm_ver = process.system_output(cmd_get_tpm_ver,
                                                   shell=True).decode().strip()
            logging.info('The TPM device version is %s.', actual_tpm_ver)
            required_tmp_ver = params.get('required_tmp_version')
            if actual_tpm_ver != required_tmp_ver:
                test.cancel('Cancel to test due to require TPM device version %s, '
                            'actual version: %s' % (required_tmp_ver, actual_tpm_ver))

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    for _ in range(params.get_numeric('repeat_times', 1)):
        sessions = []
        vms = env.get_all_vms()
        for vm in vms:
            vm.verify_alive()
            sessions.append(vm.wait_for_login())
        for vm, session in zip(vms, sessions):
            error_context.context("%s: Check TPM info inside guest." % vm.name,
                                  logging.info)
            for name in params.get('check_cmd_names').split():
                if name:
                    pattern = params.get('pattern_output_%s' % name)
                    cmd = params.get('cmd_%s' % name)
                    search_keywords(pattern, session.cmd(cmd))

            reboot_method = params.get("reboot_method")
            if reboot_method:
                error_context.context("Reboot guest '%s'." % vm.name, logging.info)
                vm.reboot(session, reboot_method).close()
                continue

            error_context.context("Check TPM info on host.", logging.info)
            cmd_check_log = params.get('cmd_check_log')
            if cmd_check_log:
                output = process.system_output(cmd_check_log).decode()
                pattern = params.get('pattern_check_log')
                search_keywords(pattern, output)
            session.close()
