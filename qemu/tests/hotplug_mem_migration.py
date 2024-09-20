import logging
import math
import re
import time
from decimal import Decimal

from virttest import utils_test
from virttest.utils_misc import NumaInfo
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Hotplug memory to guest and check memory inside guest
    3) Run stress tests inside guest
    4) Send a migration command to the source VM and wait until it's finished
    5) Check if memory size is correct inside guest in destination
    6）Unplug memory device and check it
    7) Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _check_online_mem(session):
        mem_device = session.cmd_output(cmd_check_online_mem, timeout=10)
        LOG_JOB.info(mem_device)
        online_mem = re.search(r"online memory:\s+\d+(\.\d*)?G", mem_device).group()
        online_mem = re.search(r"\d+(\.\d*)?", online_mem).group()
        return Decimal(online_mem)

    def _compare_mem_size(online_mem, expect_mem_size):
        if Decimal(online_mem) != expect_mem_size:
            test.fail(
                "The online mem size is %sG not match expected memory"
                " %sG" % (online_mem, expect_mem_size)
            )

    cmd_check_online_mem = params.get("cmd_check_online_mem")
    cmd_new_folder = params.get("cmd_new_folder")
    numa_test = params.get("numa_test")
    mem_plug_size = params.get("size_mem")
    target_mems = params["target_mems"]

    vm = env.get_vm(params["main_vm"])
    utils_test.update_boot_option(vm, args_added="movable_node")
    session = vm.wait_for_login()

    numa_info = NumaInfo(session=session)
    mem_plug_size = Decimal(re.search(r"\d+", mem_plug_size).group())
    expect_mem_size = _check_online_mem(session)
    hotplug_test = MemoryHotplugTest(test, params, env)
    for target_mem in target_mems.split():
        hotplug_test.hotplug_memory(vm, target_mem)
        hotplug_test.check_memory(vm)
        expect_mem_size += mem_plug_size

    online_mem = _check_online_mem(session)
    _compare_mem_size(online_mem, expect_mem_size)
    for node in numa_info.get_online_nodes():
        LOG_JOB.info("Use the hotplug memory by numa %s.", node)
        session.cmd(cmd_new_folder)
        free_size = float(numa_info.read_from_node_meminfo(node, "MemFree"))
        session.cmd(numa_test % (node, math.floor(free_size * 0.9)), timeout=600)
    try:
        stress_args = params.get("stress_args")
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
    except utils_test.StressError as info:
        test.error(info)
    time.sleep(60)
    stress_test.unload_stress()
    stress_test.clean()
    # do migration
    mig_timeout = params.get_numeric("mig_timeout", 1200, float)
    mig_protocol = params.get("migration_protocol", "tcp")
    vm.migrate(mig_timeout, mig_protocol, env=env)
    for target_mem in target_mems.split():
        hotplug_test.unplug_memory(vm, target_mem)
        hotplug_test.check_memory(vm)
        expect_mem_size -= mem_plug_size

    online_mem = _check_online_mem(session)
    _compare_mem_size(online_mem, expect_mem_size)
    vm.reboot()
