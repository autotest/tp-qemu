import math
import os

from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_test
from virttest.staging import utils_memory


def max_mem_map_node(host_numa_node, qemu_pid):
    """
    Find the numa node which qemu process memory maps to it the most.

    :param numa_node_info: Host numa node information
    :type numa_node_info: NumaInfo object
    :param qemu_pid: process id of qemu
    :type numa_node_info: string
    :return: The node id and how many pages are mapped to it
    :rtype: tuple
    """
    node_list = host_numa_node.online_nodes
    memory_status, _ = utils_test.qemu.get_numa_status(host_numa_node, qemu_pid)
    node_map_most = 0
    memory_sz_map_most = 0
    for index in range(len(node_list)):
        if memory_sz_map_most < memory_status[index]:
            memory_sz_map_most = memory_status[index]
            node_map_most = node_list[index]
    return (node_map_most, memory_sz_map_most)


@error_context.context_aware
def run(test, params, env):
    """
    Qemu numa stress test:
    1) Boot up a guest and find the node it used
    2) Try to allocate memory in that node
    3) Run memory heavy stress inside guest
    4) Check the memory use status of qemu process
    5) Repeat step 2 ~ 4 several times


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    host_numa_node = utils_misc.NumaInfo()
    if len(host_numa_node.online_nodes) < 2:
        test.cancel("Host only has one NUMA node, skipping test...")

    tmp_directory = "/var/tmp"
    mem_map_tool = params.get("mem_map_tool")
    cmd_cp_mmap_tool = params.get("cmd_cp_mmap_tool")
    cmd_mmap_cleanup = params.get("cmd_mmap_cleanup") % tmp_directory
    cmd_mmap_stop = params.get("cmd_mmap_stop")
    cmd_migrate_pages = params.get("cmd_migrate_pages")
    mem_ratio = params.get_numeric("mem_ratio", 0.6, float)
    timeout = params.get_numeric("login_timeout", 240, float)
    test_count = params.get_numeric("test_count", 2, int)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    qemu_pid = vm.get_pid()
    node_list = host_numa_node.online_nodes
    node_meminfo = host_numa_node.read_from_node_meminfo
    if test_count < len(node_list):
        test_count = len(node_list)
    try:
        test_mem = float(params.get("mem")) * mem_ratio
        guest_stress_args = "-a -p -l %sM" % int(test_mem)
        stress_path = os.path.join(data_dir.get_deps_dir("mem_mapping"), mem_map_tool)
        test.log.info("Compile the mem_mapping tool")
        cmd_cp_mmap_tool = cmd_cp_mmap_tool % (
            stress_path,
            tmp_directory,
            tmp_directory,
        )
        process.run(cmd_cp_mmap_tool, shell=True)
        utils_memory.drop_caches()
        for test_round in range(test_count):
            cmd_mmap = params.get("cmd_mmap")
            error_context.context(
                "Executing stress test round: %s" % test_round, test.log.info
            )
            try:
                error_context.context(
                    "Get the qemu process memory use status", test.log.info
                )
                most_used_node, memory_used = max_mem_map_node(host_numa_node, qemu_pid)
                numa_node_malloc = most_used_node
                mmap_size = math.floor(
                    float(node_meminfo(numa_node_malloc, "MemTotal")) * mem_ratio
                )
                cmd_mmap = cmd_mmap % (tmp_directory, numa_node_malloc, mmap_size)
                error_context.context(
                    "Run mem_mapping on host node " "%s." % numa_node_malloc,
                    test.log.info,
                )
                process.system(cmd_mmap, shell=True, ignore_bg_processes=True)
                error_context.context("Run memory heavy stress in guest", test.log.info)
                try:
                    guest_stress = utils_test.VMStress(
                        vm,
                        "mem_mapping",
                        params,
                        download_url=stress_path,
                        stress_args=guest_stress_args,
                    )
                    guest_stress.load_stress_tool()
                except utils_test.StressError as guest_info:
                    test.error(guest_info)
                error_context.context(
                    "Get the qemu process memory use status", test.log.info
                )
                node_after, memory_after = max_mem_map_node(host_numa_node, qemu_pid)
                if node_after == most_used_node and memory_after >= memory_used:
                    idle_nodes = node_list.copy()
                    idle_nodes.remove(numa_node_malloc)
                    error_context.context(
                        "Run migratepages on host from node "
                        "%s to node %s." % (numa_node_malloc, idle_nodes[0]),
                        test.log.info,
                    )
                    migrate_pages = cmd_migrate_pages % (
                        qemu_pid,
                        numa_node_malloc,
                        idle_nodes[0],
                    )
                    process.system_output(migrate_pages, shell=True)
                    error_context.context(
                        "Get the qemu process memory use status again", test.log.info
                    )
                    node_after, memory_after = max_mem_map_node(
                        host_numa_node, qemu_pid
                    )
                    if node_after == most_used_node and memory_after >= memory_used:
                        test.fail("Memory still stick in node %s" % numa_node_malloc)
            finally:
                guest_stress.unload_stress()
                guest_stress.clean()
                process.system(cmd_mmap_stop, shell=True, ignore_status=True)
                utils_memory.drop_caches()
    finally:
        process.run(cmd_mmap_cleanup, shell=True)
        session.close()
