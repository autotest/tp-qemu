from avocado.utils import cpu
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    1. Create the params file with kernel options for the secure image.
    2. Download the certificate for the secure image inside of the guest.
    3. Create the boot image file in side of the guest
    4. Update the zipl config inside of the guest
    5. Load updated kernel command inside of the guest and reboot
    6. Check if the guest is secured

    :params boot_img: command for securing the guest, assume the cerfication
    is already download into /home directory
    """

    def run_cmd_in_guest(session, cmd, test):
        """
        Run command in the guest

        :param vm: vm object
        :param cmd: a command needs to be ran
        :param session: the vm's session
        :param status: cmd status
        :param output: cmd output
        """
        status, output = session.cmd_status_output(cmd, timeout=60)
        test.log.info("The command of '%s' output: %s", cmd, output)
        if not status:
            return output
        else:
            test.fail("cmd runs failed cmd: %s, output: %s", cmd, output)

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login(timeout=60)

    # create the secure boot params
    secure_params_cmd = params.get("secure_params_cmd")
    run_cmd_in_guest(session, secure_params_cmd, test)

    # check LPAR type(Z15/Z16) and download HKD
    cpu_family = cpu.get_family()
    if cpu_family:
        download_hkd = params.get("download_hkd_%s" % cpu_family)
    else:
        test.fail("Failed to retrieve CPU family.")
    run_cmd_in_guest(session, download_hkd, test)  # pylint: disable=E0606

    # Create the boot image file
    kernel_version = run_cmd_in_guest(session, "uname -r", test)
    kernel_version = kernel_version.strip()
    boot_kernel = "/boot/vmlinuz-%s" % kernel_version
    boot_initrd = "/boot/initramfs-%s%s" % (kernel_version, ".img")
    boot_img_cmd = params.get("boot_img_cmd") % (boot_kernel, boot_initrd)
    run_cmd_in_guest(session, boot_img_cmd, test)

    # update the zipl config
    zipl_config_cmd = params.get("zipl_config_cmd")
    run_cmd_in_guest(session, zipl_config_cmd, test)

    # update the kernel command and reboot the guest
    zipl_cmd = params.get("zipl_cmd")
    run_cmd_in_guest(session, zipl_cmd, test)
    session.close()
    vm.reboot()

    # Check if the vm is secured
    session = vm.wait_for_login(timeout=60)
    check_se_cmd = params.get("check_se_cmd")
    se_output = run_cmd_in_guest(session, check_se_cmd, test).strip()
    if "1" == se_output:
        test.log.info("Image is secured")
    else:
        test.fail("Image failed to secured")
    session.close()
