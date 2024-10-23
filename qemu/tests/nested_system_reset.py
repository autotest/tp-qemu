from virttest import error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    System_reset in nested environment

    1. Boot L1 guest
    2. Start a qemu-kvm process in L1 guest
    3. Do system_reset for L1

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    if not utils_package.package_install("qemu-kvm", session):
        test.fail("qemu-kvm is not installed in the guest vm.")

    qemu_cmd = params.get("qemu_cmd")
    get_pid_cmd = params.get("get_pid_cmd")
    session.cmd(qemu_cmd, ignore_all_errors=True)
    qemu_pid = session.cmd_output(get_pid_cmd)

    if qemu_pid:
        reboot_cmd = params.get("reboot_cmd")
        vm.reboot(session, reboot_cmd)
    else:
        test.fail("qemu-kvm process started fail in L1 guest.")

    vm.verify_alive()
    vm.verify_kernel_crash()
    session.close()
