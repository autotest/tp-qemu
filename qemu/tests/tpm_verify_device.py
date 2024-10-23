import re

from avocado.utils import process
from virttest import env_process, error_context


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

    def search_keywords(patterns, string, flags=re.M, split_string=";"):
        test.log.info(string)
        for pattern in patterns.split(split_string):
            if not re.search(r"%s" % pattern, string, flags):
                test.fail('No Found pattern "%s" from "%s".' % (pattern, string))
            if re.search(r"error", string, re.M | re.A):
                test.error('Found errors from "%s".' % string)

    cmd_get_tpm_ver = params.get("cmd_get_tpm_version")
    cmd_check_tpm_dev = params.get("cmd_check_tpm_device")
    if cmd_check_tpm_dev:
        status, output = process.getstatusoutput(cmd_check_tpm_dev)
        if status:
            test.cancel("No found TPM device on host, output: %s" % output)
        if cmd_get_tpm_ver:
            actual_tpm_ver = (
                process.system_output(cmd_get_tpm_ver, shell=True).decode().strip()
            )
            test.log.info("The TPM device version is %s.", actual_tpm_ver)
            required_tmp_ver = params.get("required_tmp_version")
            if actual_tpm_ver != required_tmp_ver:
                test.cancel(
                    "Cancel to test due to require TPM device version %s, "
                    "actual version: %s" % (required_tmp_ver, actual_tpm_ver)
                )

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    for _ in range(params.get_numeric("repeat_times", 1)):
        sessions = []
        vms = env.get_all_vms()
        for vm in vms:
            vm.verify_alive()
            sessions.append(vm.wait_for_login())

        for vm, session in zip(vms, sessions):
            error_context.context(
                "%s: Check Windows event log inside guest before test." % vm.name,
                test.log.info,
            )
            cmd_check_event_log = params.get("cmd_check_event_log")
            event_log_pattern = params.get("pattern_output_event_log")
            if cmd_check_event_log:
                event_log = session.cmd_output(cmd_check_event_log)
                search_keywords(event_log_pattern, event_log)

            error_context.context(
                "%s: Check TPM info inside guest." % vm.name, test.log.info
            )
            for name in params.get("check_cmd_names").split():
                if name:
                    pattern = params.get("pattern_output_%s" % name)
                    cmd = params.get("cmd_%s" % name)
                    search_keywords(pattern, session.cmd(cmd))

            cmd_get_tpmsupportedfeature = params.get("cmd_get_tpmsupportedfeature")
            output_get_tpmsupportedfeature = params.get(
                "output_get_tpmsupportedfeature"
            )
            if cmd_get_tpmsupportedfeature:
                tpmspportedfeature = session.cmd(cmd_get_tpmsupportedfeature)
                search_keywords(output_get_tpmsupportedfeature, tpmspportedfeature)

            reboot_method = params.get("reboot_method")
            if reboot_method:
                error_context.context("Reboot guest '%s'." % vm.name, test.log.info)
                vm.reboot(session, reboot_method).close()
                continue

            error_context.context(
                "%s: Check Windows event log inside guest after test." % vm.name,
                test.log.info,
            )
            if cmd_check_event_log:
                event_log = session.cmd_output(cmd_check_event_log)
                search_keywords(event_log_pattern, event_log)

            error_context.context("Check TPM info on host.", test.log.info)
            cmd_check_log = params.get("cmd_check_log")
            if cmd_check_log:
                output = process.system_output(cmd_check_log).decode()
                pattern = params.get("pattern_check_log")
                search_keywords(pattern, output)
            session.close()
