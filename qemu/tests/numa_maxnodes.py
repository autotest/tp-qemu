from virttest import env_process, error_context

from qemu.tests import numa_memdev_options


@error_context.context_aware
def run(test, params, env):
    """
    [Memory][Numa]binding 128 guest nodes to node0 - x86 with 32M and Power
    with 256M, this case will:
    1) Boot guest with 128 numa nodes
    2) Check query-memdev
    3) Check memory in procfs on host
    4) Check numa node amount in guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error_context.context(
        "Modify params to boot guest with 128 numa nodes", test.log.info
    )
    node_num = int(params["numa_nodes"])
    node_size = params["node_size"]
    prealloc_mem = params.get("prealloc_mem", "no")
    mem_devs = ""
    guest_numa_nodes = ""
    for index in range(node_num):
        guest_numa_nodes += "node%s " % index
        mem_devs += "mem%s " % index
        params["numa_memdev_node%s" % index] = "mem-mem%s" % index
        params["size_mem%s" % index] = node_size
        params["prealloc_mem%s" % index] = prealloc_mem

    params["guest_numa_nodes"] = guest_numa_nodes
    params["mem_devs"] = mem_devs
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    error_context.context("Get the main VM!", test.log.info)
    vm = env.get_vm(params["main_vm"])

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    error_context.context("Check memdevs from monitor", test.log.info)
    numa_memdev_options.check_query_memdev(test, params, vm)

    error_context.context("Check memory in host procfs", test.log.info)
    numa_memdev_options.check_memory_in_procfs(test, params, vm)

    error_context.context("Check numa node for linux guest", test.log.info)
    if params["os_type"] == "linux":
        error_context.context("Check numa node in guest", test.log.info)
        numa_cmd = params["numa_cmd"]
        numa_expected = params["numa_expected"]
        guest_numa = session.cmd_output(numa_cmd).strip()
        if guest_numa != numa_expected:
            test.fail(
                "Guest numa node is %s while expected numa node is %s"
                % (guest_numa, numa_expected)
            )
    error_context.context("Check if error and calltrace in guest", test.log.info)
    vm.verify_kernel_crash()
    session.close()
