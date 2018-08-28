import time
import logging

from virttest import error_context
from virttest.utils_test.qemu import MemoryHotplugTest


class MemoryHotplugRepeat(MemoryHotplugTest):

    def start_test(self):
        """
        Prepare reqired test params, then start memory
        hotplug/unplug tests in turn. And this is test entry.
        """
        target_mem = self.params["target_mem"]
        vm = self.env.get_vm(self.params["main_vm"])
        max_slots = int(self.params.get("slots_mem", 4))
        scalability_test = self.params.get("scalability_test") == "yes"
        repeats = scalability_test and max_slots or self.params["repeats"]
        original_mem = self.get_guest_total_mem(vm)
        for repeat in range(int(repeats)):
            extra_params = (scalability_test and
                            [{'slot_dimm': repeat}] or [None])[0]
            error_context.context("Hotplug/unplug loop '%d'" % repeat,
                                  logging.info)
            self.turn(vm, target_mem, extra_params)
            current_mem = self.get_guest_total_mem(vm)
            if current_mem != original_mem:
                self.test.fail("Guest memory changed about repeat"
                               " hotpug/unplug memory %d times" % repeat)
            time.sleep(1.5)
        vm.verify_alive()
        vm.reboot()

    def turn(self, vm, target_mem, extra_params=None):
        """
        Hotplug/Unplug memory in turn

        :param vm: qemu target VM object
        :param target_mem: memory name of target VM object
        :param extra_params: params dict, that you want to update

        """
        memorys = self.get_all_memorys(vm)
        if extra_params:
            self.params.update(extra_params)
        self.hotplug_memory(vm, target_mem)
        memorys_added = self.get_all_memorys(vm) - memorys
        offline_memorys = self.get_offline_memorys(vm)
        time.sleep(1.5)
        for memory in offline_memorys:
            # Online memory to movable zone maybe failed, see details
            # in redhat Bug 1314306
            self.memory_operate(vm, memory, 'online_movable')
        for memory in memorys_added:
            self.memory_operate(vm, memory, 'offline')
        time.sleep(1.5)
        self.unplug_memory(vm, target_mem)


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Hotplug/unplug memory in turn
    3) Reboot VM

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    hotplug_test = MemoryHotplugRepeat(test, params, env)
    hotplug_test.start_test()
