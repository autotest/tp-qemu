import re

from virttest import env_process, error_context, utils_misc
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    numa_node_affinity test
    1) Check the NUMA topology, cancel if there is a single node.
    2) Boot up a guest with node-affinity selecting the first valid node.
    3) Check the cpu-affinity obtained from QEMU is correct.
    4) Check the node-affinity property is not readable.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.online_nodes_withcpu
    if len(node_list) < 2:
        test.cancel("Host only has one NUMA node, skipping test...")

    error_msg = params.get(
        "error_msg", "Property 'thread-context.node-affinity' is not readable"
    )
    node_affinity = node_list[0]
    node = utils_misc.NumaNode(node_affinity)
    tc_options = "node-affinity=%d" % node_affinity
    params["vm_thread_context_options_tc1"] = tc_options
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()

    thread_context_device = vm.devices.get_by_params({"backend": "thread-context"})[0]
    thread_context_device_id = thread_context_device.get_param("id")

    error_context.base_context("Get the CPU affinity", test.log.info)
    cpu_affinity = vm.monitor.qom_get(thread_context_device_id, "cpu-affinity")
    cpu_affinity = list(map(str, cpu_affinity))
    error_context.base_context("Get the host node cpus", test.log.info)
    host_node_cpus = node.get_node_cpus(node_affinity).split()

    if cpu_affinity != host_node_cpus:
        test.fail("The cpu-affinity does not match with the node topology!")

    try:
        error_context.base_context("Trying to read node-affinity", test.log.info)
        node_affinity = vm.monitor.qom_get(thread_context_device_id, "node-affinity")
    except QMPCmdError as e:
        if not re.search(error_msg, str(e.data)):
            test.fail("Cannot get expected error message: %s" % error_msg)
        test.log.debug("Get the expected error message: %s", error_msg)
    else:
        test.fail(
            "Got the node-affinity: %s however it is expected to be a non-readable "
            "property" % str(node_affinity)
        )
