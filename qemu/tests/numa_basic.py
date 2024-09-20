from virttest import env_process, error_context, utils_misc, utils_test
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    Qemu numa basic test:
    1) Get host numa topological structure
    2) Start a guest and bind it on the cpus of one node
    3) Check the memory status of qemu process. It should mainly use the
       memory in the same node.
    4) Destroy the guest
    5) Repeat step 2 ~ 4 on every node in host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Get host numa topological structure", test.log.info)
    timeout = float(params.get("login_timeout", 240))
    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.online_nodes
    for node_id in node_list:
        error_context.base_context(
            "Bind qemu process to numa node %s" % node_id, test.log.info
        )
        vm = "vm_bind_to_%s" % node_id
        params["qemu_command_prefix"] = "numactl --cpunodebind=%s" % node_id
        utils_memory.drop_caches()
        node_MemFree = int(host_numa_node.read_from_node_meminfo(node_id, "MemFree"))
        if node_MemFree < int(params["mem"]) * 1024:
            test.cancel("No enough free memory in node %d." % node_id)
        env_process.preprocess_vm(test, params, env, vm)
        vm = env.get_vm(vm)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        session.close()

        error_context.context(
            "Check the memory use status of qemu process", test.log.info
        )
        memory_status, _ = utils_test.qemu.get_numa_status(host_numa_node, vm.get_pid())
        node_used_most = 0
        memory_sz_used_most = 0
        for index in range(len(node_list)):
            if memory_sz_used_most < memory_status[index]:
                memory_sz_used_most = memory_status[index]
                node_used_most = node_list[index]
            test.log.debug(
                "Qemu used %s pages in node" " %s",
                memory_status[index],
                node_list[index],
            )
        if node_used_most != node_id:
            test.fail(
                "Qemu still use memory from other node. "
                "Expect: %s, used: %s" % (node_id, node_used_most)
            )
        error_context.context("Destroy guest.", test.log.info)
        vm.destroy()
