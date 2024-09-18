from virttest import env_process, error_context

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu flag nonstop_tsc.
    1) Check if current flags are in the supported lists on host, if no, cancel test
    2) Otherwise, boot guest with the cpu flag 'invtsc'
    3) Check cpu flags inside guest(only for linux guest and not for RHEL6)
    4) Check tsc inside guest(only for linux guest)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    flag = params["flags"]
    check_host_flags = params.get_boolean("check_host_flags")
    if check_host_flags:
        check_cpu_flags(params, flag, test)

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()
    if params["os_type"] == "linux":
        if params["os_variant"] != "rhel6":
            check_cpu_flags(params, flag, test, session)
        check_clock = params["check_clock"]
        check_clock_out = session.cmd_status(check_clock)
        if check_clock_out:
            test.fail("tsc can't be found inside guest")

    if params.get("reboot_method"):
        error_context.context("Reboot guest '%s'." % vm.name, test.log.info)
        session = vm.reboot(session=session)

    vm.verify_kernel_crash()
    session.close()
