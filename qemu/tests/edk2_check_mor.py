import re

from avocado.utils import process
from avocado.utils.path import CmdNotFoundError, find_command
from virttest import env_process, error_context, utils_misc, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Verify MOR enabled in edk2 build

    1. Boot guest under secure mode and check if the guest is signed
    2. Check if secure boot is enabled inside guest
    3. Reboot and shutdown the guest
    4. Check MOR message after shutdown the guest

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _check_signed():
        """Check and return if guest is signed"""
        return True if re.search(sign_keyword, sign_info) else False

    package = params["package_installed"]
    install_status = utils_package.package_install(package)
    if not install_status:
        test.error(f"Failed to install {package}.")
    try:
        find_command(params["cmd_installed"])
    except CmdNotFoundError as e:
        test.error(str(e))
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()
    check_sign_cmd = params["check_sign_cmd"]
    sign_keyword = params["sign_keyword"]
    if session.cmd_status("which pesign") != 0:
        install_status = utils_package.package_install("pesign", session)
    if not install_status:
        test.error("Failed to install pesign.")
    error_context.context("Check whether secure boot has been enabled.", test.log.info)
    check_cmd = params["check_secure_boot_enabled_cmd"]
    status, output = session.cmd_status_output(check_cmd)
    if status:
        test.cancel("Secure boot is not enabled," "MOR must run under secure mode")
    error_context.context("Check whether the guest has been signed.", test.log.info)
    vmlinuz = "/boot/vmlinuz-%s" % session.cmd_output("uname -r")
    check_sign_cmd %= vmlinuz
    sign_info = session.cmd_output(check_sign_cmd)
    signed = _check_signed()
    if not signed:
        test.fail("The guest is not signed, " "but boot succeed under secure mode.")
    session.close()
    vars_dev = vm.devices.get_by_params({"node-name": "file_ovmf_vars"})[0]
    ovmf_vars_file = vars_dev.params["filename"]
    check_mor_cmd = params["check_mor_cmd"] % ovmf_vars_file
    error_context.context("Reboot and shutdown the guest.", test.log.info)
    vm.reboot()
    vm.destroy()
    if utils_misc.wait_for(vm.is_dead, 180, 1, 1):
        test.log.info("Guest managed to shutdown cleanly")
    error_context.context(
        "Check the MOR message by command '%s'." % check_mor_cmd, test.log.info
    )
    status, output = process.getstatusoutput(
        check_mor_cmd, ignore_status=True, shell=True
    )
    if status:
        test.fail(
            "Failed to run '%s', the error message is '%s'" % (check_mor_cmd, output)
        )
    mor_msg_list = params.get_list("mor_msg")
    if mor_msg_list[0] not in output or mor_msg_list[1] not in output:
        test.fail("Failed to get MOR message, the output is '%s'" % output)
