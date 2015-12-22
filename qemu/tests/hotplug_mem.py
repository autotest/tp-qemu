import logging
from virttest.utils_test import BackgroundTest
from virttest.utils_test import run_virt_sub_test
from virttest.utils_test.qemu import MemoryHotplugTest

# Make it work under both autotest-framework and avocado-framework
try:
    from avocado.utils.wait import wait_for
except ImportError:
    from autotest.client.shared.utils import wait_for

try:
    from virttest import error_context as step_engine
except ImportError:
    from autotest.client.shared.error import step_engine


class MemoryHotplugSimple(MemoryHotplugTest):

    def run_sub_test(self):
        if self.params.get("sub_type"):
            step = ("Run sub test '%s' %s %s memory device" %
                    (self.params["sub_test"],
                     self.params["stage"],
                     self.params["operation"]))
            step_engine.context(step, logging.info)
            args = (self.test, self.params, self.env, self.params["sub_type"])
            run_virt_sub_test(*args)

    def run_background_test(self):
        args = (self.test, self.params, self.env, self.params["sub_type"])
        bg_test = BackgroundTest(run_virt_sub_test, args)
        bg_test.start()
        wait_for(bg_test.is_alive, timeout=60)
        return bg_test

    def restore_memory(self, origin_vm, post_vm):
        mem_devs_post = post_vm.params.objects("mem_devs")
        mem_devs_origin = origin_vm.params.objects("mem_devs")
        if len(mem_devs_post) != len(mem_devs_origin):
            if len(mem_devs_origin) > len(mem_devs_post):
                mem_devs = set(mem_devs_origin) - set(mem_devs_post)
                vm, operation = post_vm, "hotplug"
            else:
                mem_devs = set(mem_devs_post) - set(mem_devs_origin)
                vm, operation = origin_vm, "unplug"
            func = getattr(self, "%s_memory" % operation)
            for mem_dev in mem_devs:
                func(vm, mem_dev)
                self.check_vm_memory(vm)

    def get_mem_by_name(self, vm, name):
        """
        Return memory object and pc-dimm devices by given name
        """
        devices = []
        for dtype in ["mem", "dimm"]:
            dev_qid = "%s-%s" % (dtype, name)
            devs = vm.devices.get_by_qid(dev_qid)
            if devs:
                devices.append(devs[0])
        return devices

    def start_test(self):
        try:
            target_mem = self.params["target_mem"]
            operation = self.params["operation"]
            vm = self.env.get_vm(self.params["main_vm"])
            if self.params.get("stage") == "before":
                self.run_sub_test()
            # If unplug memory not exits and test in instrcit then hotplug it
            if operation == "unplug":
                devs = self.get_mem_by_name(vm, target_mem)
                if not devs and self.params.get("strict") != "yes":
                    self.hotplug_memory(vm, target_mem)
            func_name = "%s_memory" % operation
            func = getattr(self, func_name)
            if self.params.get("stage") == "during":
                sub_test = self.run_background_test()
            func(vm, target_mem)
            if self.params.get("stage") == "during":
                test_timeout = float(self.params.get("sub_test_timeout", 3600))
                sub_test.join(timeout=test_timeout)
            if self.params.get("stage") == "after":
                self.run_sub_test()
            post_vm = self.env.get_vm(self.params["main_vm"])
            self.restore_memory(vm, post_vm)
        finally:
            self.close_sessions()


@step_engine.context_aware
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

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    hotplug_test = MemoryHotplugSimple(test, params, env)
    hotplug_test.start_test()
