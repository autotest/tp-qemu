from avocado.utils import process
from virttest import env_process, error_context, utils_misc

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu flag intel-pt.
    1) Check if current flags are in the supported lists, if no, cancel test
    2) Otherwise, set pt_mode = 1 on host at first
    3) Boot guest with cpu model 'host' without intel-pt.
    4) Check cpu flags in guest(only for linux guest)
    5) For q35
       5.1) boot guest with cpu model with intel-pt
    6) For pc
       6.1) boot guest with intel-pt and min-level=0x14
    7) Check cpu flags in guest(only for linux guest)
    8) Restore pt_mode value on host at last

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    flags = params["flags"]
    check_cpu_flags(params, flags, test)

    set_pt_mode = params.get("set_pt_mode")
    get_pt_mode = params.get("get_pt_mode")
    origin_value = process.getoutput(get_pt_mode).strip()

    try:
        if origin_value != "1":
            process.system(set_pt_mode % "1", shell=True)
        pt_mode = process.getoutput(get_pt_mode).strip()
        if pt_mode != "1":
            test.cancel("pt_mode can't be set to 1")

        params["start_vm"] = "yes"
        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        error_context.context("Try to log into guest", test.log.info)
        session = vm.wait_for_login()
        if params["os_type"] == "linux":
            check_cpu_flags(params, flags, test, session)
        vm.verify_kernel_crash()
        session.close()
        utils_misc.wait_for(vm.destroy, 240)
    finally:
        process.system(set_pt_mode % origin_value, shell=True)
