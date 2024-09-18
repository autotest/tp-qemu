from virttest import env_process

from provider.cpu_utils import check_cpu_flags


def run(test, params, env):
    """
    avic test:
    1) Turn on avic on Genoa host
    2) Launch a guest
    3) Check no error in guest
    4) Restore env, turn off avic

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    flags = params["flags"]
    check_cpu_flags(params, flags, test)

    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    env_process.preprocess_vm(test, params, env, vm.name)
    timeout = float(params.get("login_timeout", 240))

    vm.wait_for_login(timeout=timeout)
    vm.verify_kernel_crash()
