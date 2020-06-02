def run(test, params, env):
    """
    Reboot test with hv_reset flag:
    1) Log into a guest
    2) Send a reboot command in guest
    3) Wait until the guest is up again
    4) Log into the guest to verify it's up again

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.

    """
    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.reboot(vm.wait_for_login(timeout=360))
    vm.verify_alive()
