import time
import logging

from virttest.utils_test.qemu import MemoryHotplugTest

try:
    from virttest import error_context
except ImportError:
    from autotest.client.shared import error as error_context


class MemoryHotplugInLoop(MemoryHotplugTest):

    def start_test(self):
        """
        Prepare reqired test params, then start memory
        hotplug/unplug tests in loop. This is test entry.
        """
        mems = []
        vm = self.env.get_vm(self.params["main_vm"])
        memorys = self.get_all_memorys(vm)
        for repeat in xrange(int(self.params.get("slots_mem", 256))):
            mem_tag = "mem%d" % repeat
            mem_devs = self.params.get("memdevs", "")
            extra_params = {"memdevs": " ".join([mem_devs, mem_tag]),
                            "slot_dimm_%s" % mem_tag: repeat}
            self.params.update(extra_params)
            error_context.context("Hotplug the '%s' memory" % mem_tag,
                                  logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            self.hotplug_memory(vm, mem_tag)
            mems.append(mem_tag)
            time.sleep(0.5)
        memorys_added = self.get_all_memorys(vm) - memorys
        offline_memorys = self.get_offline_memorys(vm)
        for memory in offline_memorys:
            # Online memory to movable zone maybe failed, see details
            # in redhat Bug 1314306
            self.memory_operate(vm, memory, 'online_movable')
            time.sleep(0.5)
        self.check_memory()
        for memory in memorys_added:
            self.memory_operate(vm, memory, 'offline')
            time.sleep(0.5)

        vm = self.env.get_vm(self.params["main_vm"])
        for mem in mems:
            self.unplug_memory(vm, mem_tag)
        del mems

        vm = self.env.get_vm(self.params["main_vm"])
        vm.verify_alive()
        vm.reboot()


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Hotplug memory device in loop
    3) Online hotpluged memory device in guest
    4) Check memory size in guest
    5) Offline memory in guest
    6) Unplug memory device in loop
    7) Check memory size in guest
    8) Reboot VM to check guest bootable.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    hotplug_test = MemoryHotplugInLoop(test, params, env)
    hotplug_test.start_test()
