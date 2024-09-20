import time

from virttest import utils_test
from virttest.utils_test.qemu import MemoryHotplugTest


def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Hotplug memory to guest and check memory inside guest
    3) Run stress tests inside guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()
    mem_name = params["target_mems"]
    hotplug_test = MemoryHotplugTest(test, params, env)
    hotplug_test.hotplug_memory(vm, mem_name)
    hotplug_test.check_memory(vm)
    if params["os_type"] == "linux":
        stress_args = params.get("stress_args")
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
        time.sleep(60)
        stress_test.unload_stress()
