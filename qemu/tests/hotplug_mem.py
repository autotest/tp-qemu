import logging
import time

from avocado.utils.wait import wait_for
from virttest import error_context, utils_test
from virttest.utils_test import BackgroundTest, run_virt_sub_test
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


class MemoryHotplugSimple(MemoryHotplugTest):
    def run_sub_test(self):
        """Run virt sub test before/after hotplug/unplug memory device"""
        if self.params.get("sub_type"):
            step = "Run sub test '%s' %s %s memory device" % (
                self.params["sub_test"],
                self.params["stage"],
                self.params["operation"],
            )
            error_context.context(step, LOG_JOB.info)
            args = (self.test, self.params, self.env, self.params["sub_type"])
            run_virt_sub_test(*args)

    def run_background_test(self):
        """Run virt sub test in backgroup"""
        wait_time = float(self.params.get("sub_test_wait_time", 0))
        args = (self.test, self.params, self.env, self.params["sub_type"])
        bg_test = BackgroundTest(run_virt_sub_test, args)
        bg_test.start()
        wait_for(bg_test.is_alive, first=wait_time, step=3, timeout=240)
        return bg_test

    def restore_memory(self, pre_vm, post_vm):
        """
        Compare pre_vm and post_vm, restore VM memory devices.
        """
        mem_devs_post = set(post_vm.params.objects("mem_devs"))
        mem_devs_origin = set(pre_vm.params.objects("mem_devs"))
        if mem_devs_post == mem_devs_origin:
            return
        if len(mem_devs_origin) > len(mem_devs_post):
            mem_devs = mem_devs_origin - mem_devs_post
            vm, operation = post_vm, "hotplug"
        elif len(mem_devs_origin) < len(mem_devs_post):
            mem_devs = mem_devs_post - mem_devs_origin
            vm, operation = pre_vm, "unplug"
        func = getattr(self, "%s_memory" % operation)  # pylint: disable=E0606
        for mem_dev in mem_devs:  # pylint: disable=E0606
            func(vm, mem_dev)  # pylint: disable=E0606

    def get_mem_by_name(self, vm, name):
        """
        Return memory object and pc-dimm devices by given name
        """
        dev_ids = map(lambda x: "-".join([x, name]), ["mem", "dimm"])
        devices = filter(None, map(vm.devices.get_by_qid, dev_ids))
        return [_[0] for _ in devices]

    def unplug_memory(self, vm, target_mem):
        """Unplug the target memory, if the memory not exists,
        hotplug it, then unplug it
        """
        devs = self.get_mem_by_name(vm, target_mem)
        if not devs and self.params.get("strict_check") != "yes":
            self.hotplug_memory(vm, target_mem)
        return super(MemoryHotplugSimple, self).unplug_memory(vm, target_mem)

    def start_test(self):
        operation = self.params["operation"]
        target_mems = self.params["target_mems"]
        stage = self.params.get("stage", "before")
        login_timeout = int(self.params.get("login_timeout", 360))
        sub_test_runner = (
            stage == "during" and [self.run_background_test] or [self.run_sub_test]
        )[0]
        func = getattr(self, "%s_memory" % operation)
        if not callable(func):
            self.test.error("Unsupported memory operation '%s'" % operation)
        vm = self.env.get_vm(self.params["main_vm"])
        vm.wait_for_login(timeout=login_timeout)
        bootup_time = time.time() - vm.start_time
        utils_test.update_boot_option(vm, args_added="movable_node")
        try:
            if stage != "after":
                sub_test = sub_test_runner()
                if self.params.get("sub_type") == "boot":
                    time.sleep(bootup_time / 2)
                for target_mem in target_mems.split():
                    func(vm, target_mem)
                    self.check_memory(vm)
            else:
                for target_mem in target_mems.split():
                    func(vm, target_mem)
                    self.check_memory(vm)
                sub_test = sub_test_runner()
            if stage == "during":
                sub_test.join(timeout=3600)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.reboot()
        finally:
            try:
                self.restore_memory(vm, self.env.get_vm(self.params["main_vm"]))
            except Exception as details:
                LOG_JOB.warning("Error happen when restore vm: %s", details)
            self.close_sessions()


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Run sub test before hotplug/unplug memory device
    3) Hotplug/unplug  memory device
    4) Check hotpluged memory detect in guest OS
    5) Check no calltrace in guest/host dmesg
    6) Hotplug/unplug memory device
    7) Run sub test after plug/unplug memory device
    8) Restore VM and reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    hotplug_test = MemoryHotplugSimple(test, params, env)
    hotplug_test.start_test()
