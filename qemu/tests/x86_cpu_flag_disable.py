import random

from virttest import env_process, error_context

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu flags.
    1) Check if current flags are in the supported lists, if no, cancel test
    2) Otherwise, boot guest with the cpu flags disabled
    3) Check cpu flags inside guest(only for linux guest)
    4) Check kvmclock inside guest(only for linux guest)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    flags_list = params.objects("flags_list")
    params["flags"] = params["no_flags"] = random.choice(flags_list)
    flag = params["flags"]
    params["cpu_model_flags"] += ",-%s" % flag

    check_host_flags = params.get_boolean("check_host_flags")
    if check_host_flags:
        check_cpu_flags(params, flag, test)

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()
    check_cpu_flags(params, "", test, session)

    if flag == "kvmclock":
        check_clock = params.get("check_clock")
        vm_clock_out = session.cmd_output(check_clock).split()
        if "kvmclock" in vm_clock_out:
            test.fail("kvmclock shouldn't be found inside geust")

    vm.verify_kernel_crash()
    session.close()
