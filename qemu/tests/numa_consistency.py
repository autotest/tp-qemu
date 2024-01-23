from virttest import env_process
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test

from virttest.staging import utils_memory
from provider.memory_benchmark import generate_instance


def get_node_used_memory(qemu_pid, node):
    """
    Return the memory used by the NUMA node

    :param qemu_pid: the process id of qemu-kvm
    :param node: the NUMA node
    """
    qemu_memory_status = utils_memory.read_from_numa_maps(qemu_pid,
                                                          "N%d" % node)
    used_memory = sum([int(_) for _ in list(qemu_memory_status.values())])
    return used_memory


@error_context.context_aware
def run(test, params, env):
    """
    QEMU numa consistency test:
    1) Get host numa topological structure
    2) Start a guest binded to one host NUMA node
    3) Allocate memory inside the guest
    4) The memory used in host should increase for the corresponding
    node

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.online_nodes_withcpumem
    if len(node_list) < 2:
        test.cancel("Host only has one NUMA node, skipping test...")

    node_alloc = node_list[0]
    node_mem_alloc = int(host_numa_node.read_from_node_meminfo(node_alloc,
                                                               'MemFree'))
    # Get the node with more free memory
    for node in node_list[1:]:
        node_mem_free = int(host_numa_node.read_from_node_meminfo(node,
                                                                  'MemFree'))
        if node_mem_free > node_mem_alloc:
            node_mem_alloc = node_mem_free
            node_alloc = node

    mem_ratio = params.get_numeric("mem_ratio", 0.3, float)
    timeout = params.get_numeric("login_timeout", 240, float)
    params["vm_mem_host_nodes"] = str(node_alloc)
    params["qemu_command_prefix"] = "numactl -m %d " % node_alloc
    params["start_vm"] = "yes"

    vm_name = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    qemu_pid = vm.get_pid()
    try:
        test_mem = float(params.get("mem")) * mem_ratio
        guest_stress_args = params.get("guest_stress_args", "-a -p -l %sM")
        guest_stress_args = guest_stress_args % int(test_mem)
        utils_memory.drop_caches()
        error_context.base_context("Get the qemu memory use for node: %d before stress"
                                   % node_alloc, test.log.info)
        memory_before = get_node_used_memory(qemu_pid, node_alloc)
        try:
            mmap = generate_instance(params, vm, 'mmap')
            mmap.run(guest_stress_args, session, 20)
        except utils_test.StressError as guest_info:
            test.error(guest_info)
        mmap.clean(timeout=10, force=True)
        utils_memory.drop_caches()
        error_context.context("Get the qemu memory used in node: %d after stress"
                              % node_alloc, test.log.debug)
        memory_after = get_node_used_memory(qemu_pid, node_alloc)
        test.log.debug("memory_before %d, memory_after: %d"
                       % (memory_before, memory_after))
        if memory_after <= memory_before:
            test.error("Memory usage has not increased after the allocation!")
    finally:
        session.close()
