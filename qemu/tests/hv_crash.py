from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test the hv_crash flag avaliability

    1) boot the guest with hv_crash flag
    2) use nmi to make the guest crash, the qemu process should quit
    3) boot the guest without hv_crash flag
    4) use nmi again, the qemu should not quit

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _boot_guest_with_cpu_flag(hv_flag):
        """
        Boot the guest, with param cpu_model_flags set to hv_flag

        param hv_flag: the hv flags to set to cpu
        return: the booted vm
        """
        params["cpu_model_flags"] = hv_flag
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        return vm, session

    def _trigger_crash(vm, session):
        """
        Trigger a system crash by nmi
        """
        session.cmd(set_nmi_cmd)
        vm.reboot(session=session, timeout=timeout)
        vm.monitor.nmi()

    timeout = params.get("timeout", 360)
    hv_crash_flag = params["hv_crash_flag"]
    set_nmi_cmd = params["set_nmi_cmd"]
    flags_without_hv_crash = params["cpu_model_flags"]
    flags_with_hv_crash = flags_without_hv_crash + "," + hv_crash_flag

    error_context.context("Boot the guest with hv_crash flag", test.log.info)
    vm, session = _boot_guest_with_cpu_flag(flags_with_hv_crash)

    error_context.context("Make the guest crash", test.log.info)
    _trigger_crash(vm, session)
    test.log.info("Check the qemu process is quit")
    if not utils_misc.wait_for(vm.is_dead, 10, 1, 1):
        test.fail("The qemu still active after crash")

    error_context.context("Boot the guest again", test.log.info)
    vm, session = _boot_guest_with_cpu_flag(flags_without_hv_crash)

    error_context.context("Make the guest crash again", test.log.info)
    _trigger_crash(vm, session)
    test.log.info("Check the qemu process is not quit")
    if utils_misc.wait_for(vm.is_dead, 10, 1, 1):
        test.fail("The qemu is quit after crash")
