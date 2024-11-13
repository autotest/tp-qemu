import re

from virttest import cpu, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test the vIOMMU platform.

    Steps:
        1. Add "intel_iommu=on" to kernel line of q35 guest.
        2. Boot a guest with virtio-scsi with iommu_platform=on.
        3. Verify IOMMU enabled in the guest.
        4. Execute a simple I/O in the disk
        5. Reload kernel then reboot guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_boot_file(cmd_get_boot_file):
        """Get the boot file."""
        current_kernel = session.cmd_output(params.get("cmd_get_kernel_ver"))
        boot_files = session.cmd_output(cmd_get_boot_file).splitlines()
        if len(boot_files) > 1:
            for boot_file in boot_files:
                if current_kernel not in boot_file:
                    return boot_file
        return boot_files[0]

    def reload_kernel(session):
        """Reload kernel."""
        error_context.context("Reload kernel.", test.log.info)
        vmlinuz = _get_boot_file(params.get("cmd_get_boot_vmlinuz"))
        initrd = _get_boot_file(params.get("cmd_get_boot_initramfs"))
        orig_cmdline = session.cmd_output(params.get("cmd_get_boot_cmdline"))
        new_cmdline = re.sub(r"vmlinuz\S+", vmlinuz, orig_cmdline).strip()
        session.cmd(params.get("reload_kernel_cmd") % (vmlinuz, initrd, new_cmdline))

    def verify_iommu_enabled():
        """Verify whether the iommu is enabled."""
        error_context.context(
            "Verify whether IOMMU is enabled in the guest.", test.log.info
        )
        for key_words in params["check_key_words"].split(";"):
            output = session.cmd_output('journalctl -k | grep -i "%s"' % key_words)
            if not output:
                test.fail(
                    'No found the info "%s" '
                    "from the systemd journal log." % key_words
                )
            test.log.debug(output)

    if cpu.get_cpu_vendor(verbose=False) != "GenuineIntel":
        test.cancel("This case only support Intel platform.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)
    verify_iommu_enabled()

    session.cmd(params.get("dd_cmd"))

    if params.get("reload_kernel_cmd"):
        reload_kernel(session)

    session = vm.reboot(session, timeout=360)
    session.cmd(params.get("dd_cmd"))
