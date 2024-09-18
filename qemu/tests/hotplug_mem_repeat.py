import logging

from virttest import error_context, utils_test
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


class MemoryHotplugRepeat(MemoryHotplugTest):
    def repeat_hotplug(self, vm, target_mems):
        """
        Hotplug memory in target_mems
        :param vm: vm object in this test
        :param target_mems: target memory to be hotplugged
        """
        for target_mem in target_mems:
            self.hotplug_memory(vm, target_mem)
        self.check_memory(vm)

    def repeat_unplug(self, vm, target_mems):
        """
        Unplug memory in target_mems
        :param vm: vm object in this test
        :param target_mems: target memory to be unplugged
        """
        for target_mem in target_mems:
            self.unplug_memory(vm, target_mem)
        self.check_memory(vm)

    def start_test(self):
        """
        Prepare required test params, then for scalability test, hotplug
        memory 256 times, then unplug 256 times. Otherwise, repeat hotplug
        and unplug in turn for 256 times. This is test entry.
        """
        times = self.params.get_numeric("repeat_times", int)
        target_mems = []
        for i in range(times):
            target_mems.append("mem%s" % i)
        vm = self.env.get_vm(self.params["main_vm"])
        session = vm.wait_for_login()
        if self.params.get("vm_arch_name", "") == "aarch64":
            self.test.log.info("Check basic page size on guest.")
            get_basic_page = self.params.get("get_basic_page")
            if session.cmd(get_basic_page).strip() == "65536":
                self.params["size_mem"] = self.params.get("size_mem_64k")
        if self.params.get_boolean("mem_unplug_test", False):
            arg = "movable_node"
            utils_test.update_boot_option(vm, args_added=arg)
        original_mem = self.get_guest_total_mem(vm)
        if self.params["test_type"] == "scalability_test":
            error_context.context(
                "Repeat hotplug memory for %s times" % times, LOG_JOB.info
            )
            self.repeat_hotplug(vm, target_mems)
            if self.params.get_boolean("mem_unplug_test", False):
                error_context.context(
                    "Repeat unplug memory for %s times" % times, LOG_JOB.info
                )
                self.repeat_unplug(vm, target_mems)
        else:
            for target_mem in target_mems:
                error_context.context(
                    "Hotplug and unplug memory %s" % target_mem, LOG_JOB.info
                )
                self.hotplug_memory(vm, target_mem)
                if self.params.get_boolean("mem_unplug_test", False):
                    self.unplug_memory(vm, target_mem)

        if self.params.get_boolean("mem_unplug_test", False):
            current_mem = self.get_guest_total_mem(vm)
            if current_mem != original_mem:
                self.test.fail(
                    "Guest memory changed about repeat"
                    " hotpug/unplug memory %d times" % times
                )
        vm.verify_kernel_crash()
        session.close()


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) For scalability test, hotplug memory 256 times, then unplug 256 times
    3) Otherwise, repeat hotplug and unplug in turn for 256 times

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    hotplug_test = MemoryHotplugRepeat(test, params, env)
    hotplug_test.start_test()
