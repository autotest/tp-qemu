import logging
import re

from virttest import error_context
from virttest import env_process
from virttest import utils_numeric

from virttest.utils_test import utils_memory
from virttest.utils_test.qemu import MemoryBaseTest


@error_context.context_aware
def run(test, params, env):
    """
    Qemu backend file option share, discard-data test.
    Steps:
    1) System setup hugepages on host.
    2) Mount this hugepages to /mnt/kvm_hugepage.
    3) Set backend file option share and assigned 1G mem.
    4) Check memory actually allocated on HMP.
    5) Check guest memory increased.
    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    hugepage_size = utils_memory.get_huge_page_size()
    params["target_hugepages"] = str(((params.get_numeric("mem") +
                                       params.get_numeric("size_mem")) *
                                      1024) // hugepage_size)
    params["setup_hugepages"] = "yes"
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()

    mem_test = MemoryBaseTest(test, params, env)
    mem_size = int(mem_test.get_guest_total_mem(vm))

    error_context.context("Hotplug memory with memory-backend-file, "
                          "set share=on, discard-data=on.", logging.info)
    for cmd in ["hotplug_mem_cmd", "hotplug_device_cmd", "info_cmd"]:
        output = vm.monitor.human_monitor_cmd(params[cmd])

    try:
        mem_info = re.search(r'\d{9,}', output).group(0)
    except Exception as e:
        test.fail("Failed to assigned 1G memory with error:%s" % e, logging.info)
    assign_mem = utils_numeric.normalize_data_size(mem_info)
    error_context.context("Check the '%s MB' memory actually allocated to the "
                          "guest." % assign_mem, logging.info)
    if assign_mem != params["size_mem"]:
        test.fail("Assigned '%s MB' memory to '%s', but '% s MB' memory was "
                  "actually allocated." % (params["size_mem"], vm.name, assign_mem))

    error_context.context("Check guest memory increased "
                          "by '%s MB'." % params["size_mem"], logging.info)
    mem_increment = int(mem_test.get_guest_total_mem(vm)) - mem_size
    if mem_increment != int(assign_mem):
        test.fail("Assigned '%s MB' memory to '%s', but guest memory "
                  "increased by '%s MB'." % (assign_mem, vm.name, mem_increment))

    vm.destroy()
