from virttest import cpu, env_process, error_context

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu flags.
    1) Check if current flags are in the supported lists on host, if no, cancel test
    2) Otherwise, boot guest with the cpu flags
    3) Check cpu flags inside guest(only for linux guest)
    4) Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    flags = params["flags"]
    check_host_flags = params.get_boolean("check_host_flags")
    if check_host_flags:
        check_cpu_flags(params, flags, test)

    unsupported_models = params.get("unsupported_models", "")
    cpu_model = params.get("cpu_model")
    if not cpu_model:
        cpu_model = cpu.get_qemu_best_cpu_model(params)
    if cpu_model in unsupported_models.split():
        test.cancel("'%s' doesn't support this test case" % cpu_model)
    fallback_models_map = eval(params.get("fallback_models_map", "{}"))
    if cpu_model in fallback_models_map.keys():
        params["cpu_model"] = fallback_models_map[cpu_model]

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()
    if params["os_type"] == "linux":
        if params.get("guest_flags"):
            flags = params.get("guest_flags")
        if params.get("no_flags", "") == flags:
            flags = ""
        check_guest_cmd = params.get("check_guest_cmd")
        check_cpu_flags(params, flags, test, session)
        if check_guest_cmd:
            expect_items = params.get("expect_items")
            if expect_items:
                result = session.cmd_status(check_guest_cmd % expect_items)
                if result:
                    test.fail("'%s' can't be found inside guest" % expect_items)

    if params.get("reboot_method"):
        error_context.context("Reboot guest '%s'." % vm.name, test.log.info)
        session = vm.reboot(session=session)

    vm.verify_kernel_crash()
    session.close()
