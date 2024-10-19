import logging
import time

from avocado import TestError
from virttest import error_context
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


class MemoryHotplugSimple(MemoryHotplugTest):
    def check_memory(self, vm, wait_time=0):
        """
        Check is guest memory is really match assigned to VM.

        :param vm: VM object, get VM object from env if vm is None.
        :param wait_time: time os waits after hotplug/unplug default is 0.
        """
        error_context.context("Verify guest memory size", LOG_JOB.info)
        threshold = float(self.params.get("threshold", 0.10))
        time.sleep(wait_time)
        vm_mem_size = self.get_guest_total_mem(vm)
        assigned_vm_mem_size = self.get_vm_mem(vm)
        sev_rom_size = self.params.get_numeric("sev_rom_size", 0)
        if (
            abs(vm_mem_size + sev_rom_size - assigned_vm_mem_size)
            > assigned_vm_mem_size * threshold
        ):
            msg = (
                "Assigned '%s MB' memory to '%s'"
                "but, '%s MB' memory detect by OS"
                % (assigned_vm_mem_size, vm.name, vm_mem_size)
            )
            raise TestError(msg)


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot sev-es guest.
    2) Hotplug/unplug  memory device
    3) Check hotpluged memory detect in guest OS
    4) Hotplug/unplug memory device

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start sev memory hotplug test", test.log.info)
    hotplug_test = MemoryHotplugSimple(test, params, env)
    login_timeout = params.get_numeric("login_timeout", 360)
    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login(timeout=login_timeout)

    plugged = []
    wait_time = params.get_numeric("wait_time", 0)
    for target_mem in params.objects("target_mems"):
        if target_mem in vm.params.objects("mem_devs"):
            hotplug_test.unplug_memory(vm, target_mem)
        else:
            hotplug_test.hotplug_memory(vm, target_mem)
            plugged.append(target_mem)
        hotplug_test.check_memory(vm, wait_time)

    for target_mem in plugged:
        hotplug_test.unplug_memory(vm, target_mem)
        hotplug_test.check_memory(vm, wait_time)
