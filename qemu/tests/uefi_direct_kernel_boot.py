import re

from avocado.utils import download
from virttest import data_dir, env_process, error_context, remote, utils_misc
from virttest.tests import unattended_install


@error_context.context_aware
def run(test, params, env):
    """
    Direct secure kernel boot with -shim.

    1. Install guest by OVMF environment(With OVMF_VARS.fd)
    2. Shutdown and reboot the guest with file OVMF_VARS.secboot.fd
       And add parameters -kernel, -initrd, -append and -shim
    3. Check if secure boot is enabled inside guest
    4. Check if the guest truly direct kernel boot
       If yes, no HD info in efiboot output

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Install the guest with secure boot disabled.", test.log.info)
    unattended_install.run(test, params, env)
    params["cdroms"] = ""
    params["boot_once"] = ""
    params["force_create_image"] = "no"
    params["start_vm"] = "yes"
    guest_name = params["guest_name"]
    params["kernel"] = f"images/{guest_name}/vmlinuz"
    params["initrd"] = f"images/{guest_name}/initrd.img"
    boot_efi_file = params["boot_efi_file"]
    boot_efi_dst_path = f"images/{guest_name}/{boot_efi_file}"
    boot_efi_dst_path = utils_misc.get_path(data_dir.get_data_dir(), boot_efi_dst_path)
    download_boot_efi_url = params["download_boot_efi_url"]
    download.get_file(download_boot_efi_url, boot_efi_dst_path)
    params["extra_params"] += f" -shim {boot_efi_dst_path}"
    params["kernel_params"] = params["append_option"]
    params["image_boot"] = "yes"
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"
    vm = env.get_vm(params["main_vm"])
    if vm:
        vm.destroy()
    error_context.context("Direct secure kernel boot with -shim.", test.log.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    try:
        session = vm.wait_for_serial_login()
    except remote.LoginTimeoutError:
        test.fail("The guest boots failed under secure mode.")
    else:
        check_cmd = params["check_secure_boot_enabled_cmd"]
        status = session.cmd_status(check_cmd)
        if status != 0:
            test.fail("Secure boot is not enabled")
        hd_info_pattern = params["hd_info_pattern"]
        efiboot_output_cmd = params["efiboot_output_cmd"]
        efiboot_output = session.cmd_output(efiboot_output_cmd)
        match = re.search(hd_info_pattern, efiboot_output)
        if match:
            hd_info = match.group(0)
            test.fail(
                "The guest does not truly implement direct kernel boot."
                " Get the HD info '%s' from efiboot output." % hd_info
            )
    finally:
        vm.destroy()
