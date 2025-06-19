import math
import time

import aexpect
from avocado.utils import process
from virttest import utils_misc
from virttest.staging import utils_memory


def run(test, params, env):
    """
    mlock on-fault test
    1) Boot up a VM with mem-lock=on and measure the memory usage
    2) Boot up another VM with mem-lock=on-fault and save the memory usage
    3) Validate that mem-lock=on-fault < mem-lock=on.
    4) Check the swap space and retrieve the system's memory
    5) Boot up a VM with half of the system memory with mem-lock=on-fault
    6) Execute the 'memhog' command putting more than the available memory
    7) Validate the VM doesn't swap out, i.e. RSS remains unchanged
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    qemu_path = utils_misc.get_qemu_binary(params)
    memhog_cmd = params.get("memhog_cmd")
    rss_values = []

    for status in ["on", "on-fault"]:
        qemu_cmd_memlock = params.get("qemu_cmd_memlock") % (qemu_path, status)
        try:
            with aexpect.run_bg(qemu_cmd_memlock) as _:
                qemu_pid = process.get_children_pids(_.get_pid())[0]
                rss_cmd = "ps -p %s -o rss=" % qemu_pid
                rss = process.getoutput(rss_cmd, shell=True)
                if rss:
                    rss_values.append(int(rss))
                    test.log.debug("The mem-lock=%s RSS value: %s", status, rss)
                else:
                    test.log.error("Failed to retrieve the RSS for pid: %s", qemu_pid)
        except Exception as e:
            test.log.error("An error ocurred: %s", str(e))

    if len(rss_values) < 2:
        test.fail("Unable to get the RSS for both mem-lock VMs")

    if rss_values[-1] >= rss_values[0]:
        test.fail(
            "RSS value for mem-lock on-fault is greater or equal than %d"
            % rss_values[0]
        )

    swap_free = utils_memory.read_from_meminfo("SwapFree")
    if swap_free <= 0:
        test.cancel("There is no swap free space")

    free_memory = utils_memory.read_from_meminfo("MemFree")
    vm_memory = str(free_memory // 2) + "K"
    vm_memory_normalized = math.ceil(
        float(utils_misc.normalize_data_size(vm_memory, "G"))
    )
    test.log.debug("The normalized memory size: %d", vm_memory_normalized)

    qemu_cmd_memhog = params.get("qemu_cmd_memhog") % (
        qemu_path,
        "on-fault",
        vm_memory_normalized,
        vm_memory_normalized,
    )
    test.log.info("The qemu-kvm command: %s", qemu_cmd_memhog)

    try:
        with aexpect.run_bg(qemu_cmd_memhog) as _:
            qemu_pid = process.get_children_pids(_.get_pid())[0]
            rss_cmd = "ps -p %s -o rss=" % qemu_pid
            time.sleep(5)
            previous_rss_value = int(process.getoutput(rss_cmd, shell=True))

            # Calculates a suitable amount of memory for memhog
            swap_free = str(swap_free) + "K"
            swap_normalized = math.ceil(
                float(utils_misc.normalize_data_size(swap_free, "G"))
            )
            memhog_value = math.ceil(vm_memory_normalized + (swap_normalized * 1.25))
            memhog_cmd = memhog_cmd % memhog_value
            memhog_cmd = aexpect.run_bg(memhog_cmd)

            while memhog_cmd.is_alive():
                rss_value = int(process.getoutput(rss_cmd, shell=True))
                if rss_value < previous_rss_value:
                    test.log.debug(
                        "previous_rss_value: %d and the rss_value: %d",
                        previous_rss_value,
                        rss_value,
                    )
                    test.error("The RSS value has decreased, memory is not locked!")
                previous_rss_value = rss_value
    except Exception as e:
        test.error("An error ocurred: %s" % str(e))
