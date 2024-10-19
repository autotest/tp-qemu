import random

from virttest import error_context, utils_numeric, utils_test
from virttest.utils_test.qemu import MemoryHotplugTest

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestLinux, BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Balloon and memory hotplug test:
    1) boot a guest with balloon device
    2) enable and check driver verifier in guest(only for windows guest)
    3) install balloon service in guest(only for windows guest)
    4) evict balloon
    5) hotplug memory to guest
    6) check balloon and guest memory
    7) enlarge balloon to maxium value
    8) evict balloon
    9) check balloon and guest memory
    10) uninstall balloon service and clear driver verifier(only for
       windows guest)
    """

    def check_memory():
        """
        Check guest memory
        """
        if params["os_type"] == "windows":
            memhp_test.check_memory(vm, wait_time=3)
        else:
            expected_mem = new_mem + mem_dev_sz
            guest_mem_size = memhp_test.get_guest_total_mem(vm)
            threshold = float(params.get("threshold", 0.1))
            if expected_mem - guest_mem_size > guest_mem_size * threshold:
                msg = (
                    "Assigned '%s MB' memory to '%s', "
                    "but '%s MB' memory detect by OS"
                    % (expected_mem, vm.name, guest_mem_size)
                )
                test.fail(msg)

    error_context.context("Boot guest with balloon device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    if params["os_type"] == "linux":
        balloon_test = BallooningTestLinux(test, params, env)
    else:
        driver_name = params.get("driver_name", "balloon")
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        balloon_test = BallooningTestWin(test, params, env)
        error_context.context("Config balloon service in guest", test.log.info)
        balloon_test.configure_balloon_service(session)

    memhp_test = MemoryHotplugTest(test, params, env)

    mem_dev_sz = params["size_mem"]
    mem_dev_sz = int(utils_numeric.normalize_data_size(mem_dev_sz, "M"))
    target_mem = params["target_mem"]

    try:
        min_sz, max_sz = balloon_test.get_memory_boundary()
        new_mem = int(random.uniform(min_sz, max_sz))
        balloon_test.balloon_memory(new_mem)
        memhp_test.hotplug_memory(vm, target_mem)
        check_memory()
        balloon_test.ori_mem += mem_dev_sz
        balloon_test.balloon_memory(balloon_test.ori_mem)
        min_sz, max_sz = balloon_test.get_memory_boundary()
        new_mem = int(random.uniform(min_sz, max_sz))
        balloon_test.balloon_memory(new_mem)
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        session.close()
