import re

from virttest import env_process, error_context, remote, utils_misc
from virttest.tests import unattended_install


@error_context.context_aware
def run(test, params, env):
    """
    Verify file OVMF_VARS.secboot.fd, boot released OS with Secure boot by default.

    1. Install guest by OVMF environment(With OVMF_VARS.fd)
    2. Boot guest and check if the guest is signed
    3. Shutdown and reboot the guest with file OVMF_VARS.secboot.fd
    4. Check if secure boot is enabled inside guest
    5. If *unreleased* OS boot up with secure boot, test fail

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _check_signed():
        """Check and return if guest is signed"""
        if os_type == "linux":
            return True if re.search(sign_keyword, sign_info) else False
        for device_line in sign_info.strip().splitlines()[2:]:
            if re.match(sign_keyword, device_line):
                return False
        return True

    unattended_install.run(test, params, env)
    os_type = params["os_type"]
    params["cdroms"] = ""
    params["boot_once"] = ""
    params["force_create_image"] = "no"
    params["start_vm"] = "yes"
    params["kernel"] = ""
    params["initrd"] = ""
    params["kernel_params"] = ""
    params["image_boot"] = "yes"
    vm = env.get_vm(params["main_vm"])
    if vm:
        vm.destroy()
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    check_sign_cmd = params["check_sign_cmd"]
    sign_keyword = params["sign_keyword"]
    os_type = params["os_type"]
    if os_type == "linux":
        check_pesign_cmd = "which pesign"
        if session.cmd_status(check_pesign_cmd) != 0:
            install_cmd = params["pesign_install_cmd"]
            s, o = session.cmd_status_output(install_cmd)
            if s != 0:
                test.cancel(
                    'Install pesign failed with output: "%s". '
                    "Please define proper source for guest" % o
                )
        vmlinuz = "/boot/vmlinuz-%s" % session.cmd_output("uname -r")
        check_sign_cmd = check_sign_cmd % vmlinuz
    sign_info = session.cmd_output(check_sign_cmd)
    signed = _check_signed()
    error_context.context(
        "Guest signed status is %s, shutdown and reboot "
        "guest with secure boot" % signed,
        test.log.info,
    )
    session.close()
    vm.destroy()
    if utils_misc.wait_for(vm.is_dead, 180, 1, 1):
        test.log.info("Guest managed to shutdown cleanly")
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    try:
        session = vm.wait_for_serial_login()
    except remote.LoginTimeoutError:
        if signed:
            test.fail("The guest is signed," " but boot failed under secure mode.")
    else:
        check_cmd = params["check_secure_boot_enabled_cmd"]
        status, output = session.cmd_status_output(check_cmd)
        if status != 0:
            test.fail("Secure boot is not enabled")
        if not signed:
            test.fail("The guest is not signed," " but boot succeed under secure mode.")
    finally:
        vm.destroy()
