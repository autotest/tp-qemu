import logging
import re

from avocado.utils import memory

from virttest import env_process
from virttest import error_context

from virttest.qemu_devices import qdevices
from virttest.utils_numeric import normalize_data_size
from virttest.utils_test.qemu import MemoryHotplugTest


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option.
    2) Hotplug memory with invalid params.
    3) Check qemu prompt message.
    4) Check vm is alive after hotplug.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    @error_context.context_aware
    def _hotplug_memory(vm, name):
        hotplug_test = MemoryHotplugTest(test, params, env)
        devices = vm.devices.memory_define_by_params(params, name)
        for dev in devices:
            if isinstance(dev, qdevices.Dimm):
                if params["set_addr"] == "yes":
                    addr = params["addr_dimm_%s" % name]
                else:
                    addr = hotplug_test.get_mem_addr(vm, dev.get_qid())
                dev.set_param("addr", addr)
            error_context.context("Hotplug %s '%s' to VM" %
                                  ("pc-dimm", dev.get_qid()), logging.info)
            vm.devices.simple_hotplug(dev, vm.monitor)
            hotplug_test.update_vm_after_hotplug(vm, dev)
        return devices

    def collect_hotplug_info():
        details = {}
        for target_mem in params.objects("target_mems"):
            try:
                _hotplug_memory(vm, target_mem)
            except Exception as e:
                error_context.context("Error happen %s: %s" %
                                      (target_mem, e), logging.info)
                details.update({target_mem: str(e)})
            else:
                error_context.context("Hotplug memory successful",
                                      logging.info)
                details.update({target_mem: "Hotplug memory successful"})
        return details

    def check_msg(keywords, msg):
        if not re.search(r"%s" % keywords, msg):
            test.fail("No invalid keywords were found in the qemu prompt message")

    if params["size_mem"] == "<overcommit>":
        overcommit_mem = normalize_data_size("%sK" % (memory.memtotal() * 1.2), "G")
        params["size_mem"] = "%sG" % round(float(overcommit_mem))
    if params["policy_mem"] == "bind":
        params["host-nodes"] = str(max(memory.numa_nodes()) + 1)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()

    msg = collect_hotplug_info()
    if len(params.objects("target_mems")) == 1:
        error_context.context("Check qemu prompt message.", logging.info)
        check_msg(params["keywords"], msg[params["target_mems"]])
    else:
        for target_mem in params.objects("target_mems"):
            mem_params = params.object_params(target_mem)
            error_context.context("Check %s qemu prompt "
                                  "message." % target_mem, logging.info)
            check_msg(mem_params["keywords"], msg[target_mem])
