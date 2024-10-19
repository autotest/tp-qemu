import re

from virttest import env_process, error_context
from virttest.tests import unattended_install


@error_context.context_aware
def run(test, params, env):
    """
    Unattended install test with virtual TPM device:
    1) Starts a VM with an appropriated setup to start an unattended OS install.
    2) Wait until the install reports to the install watcher its end.
    3) Check TPM device info inside guest.

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

    unattended_install.run(test, params, env)

    vm = env.get_vm(params["main_vm"])
    if vm:
        vm.destroy()

    ovmf_vars_secboot_fd = params.get("ovmf_vars_secboot_fd")
    if ovmf_vars_secboot_fd:
        params["ovmf_vars_filename"] = ovmf_vars_secboot_fd

    params["start_vm"] = "yes"
    params["cdroms"] = params.get("default_cdrom", "")
    params["force_create_image"] = "no"
    params["kernel"] = ""
    params["initrd"] = ""
    params["kernel_params"] = ""
    params["boot_once"] = "c"

    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Check TPM info inside guest.", test.log.info)
    for name in params.get("check_cmd_names").split():
        if name:
            pattern = params.get("pattern_output_%s" % name)
            cmd = params.get("cmd_%s" % name)
            search_keywords(pattern, session.cmd(cmd))

    cmd_check_secure_boot_enabled = params.get("cmd_check_secure_boot_enabled")
    if cmd_check_secure_boot_enabled:
        error_context.context(
            "Check whether secure boot enabled inside guest.", test.log.info
        )
        status, output = session.cmd_status_output(cmd_check_secure_boot_enabled)
        if status:
            test.fail("Secure boot is not enabled, output: %s" % output)
