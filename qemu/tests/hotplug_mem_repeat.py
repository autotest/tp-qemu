import time
import logging
from avocado.core import exceptions
from virttest.utils_test.qemu import MemoryHotplugTest

try:
    from virttest import error_context as step_engine
except ImportError:
    from autotest.client.shared.error import step_engine


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
        for repeat in xrange(int(repeats)):
            extra_params = (scalability_test and
                            [{'slot_dimm': repeat}] or [None])[0]
            step_engine.context(
                "Hotplug/unplug loop '%d'" %
                repeat, logging.info)
            self.turn(vm, target_mem, extra_params)
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
        if not offline_memorys.issubset(memorys_added):
            unexpected_memorys = offline_memorys - memorys_added
            exceptions.TestFail(
                "Unexpected offline memory %s" %
                unexpected_memorys)
        for memory in memorys_added:
            self.memory_operate(vm, memory, 'online_movable')
            time.sleep(1.5)
        self.check_memory(vm)
        for memory in memorys_added:
            self.memory_operate(vm, memory, 'offline')
            time.sleep(1.5)
        self.unplug_memory(vm, target_mem)
        self.check_memory(vm)


@step_engine.context_aware
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
