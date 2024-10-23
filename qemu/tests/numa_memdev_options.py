import re

from avocado.utils import astring, process
from virttest import env_process, error_context, utils_misc
from virttest.staging import utils_memory
from virttest.utils_numeric import normalize_data_size


def get_host_numa_node():
    """
    Get host NUMA node whose node size is not zero
    """
    host_numa = utils_memory.numa_nodes()
    node_list = []
    numa_info = process.getoutput("numactl -H")
    for i in host_numa:
        node_size = re.findall(r"node %d size: \d+ \w" % i, numa_info)[0].split()[-2]
        if node_size != "0":
            node_list.append(str(i))
    return node_list


def check_query_memdev(test, params, vm):
    """
    Check memory info in query-memdev

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    """
    mem_devs = params["mem_devs"].split()
    query_list = vm.monitor.info("memdev")
    if len(mem_devs) != len(query_list):
        test.fail(
            "%d memory devices in query-memdev, but not %d!"
            " query-memdev: %s"
            % (len(query_list), len(mem_devs), [item["id"] for item in query_list])
        )
    policy = params["policy_mem"]
    for dev in query_list:
        mem_dev = dev["id"].split("-")[1]
        memdev_params = params.object_params(mem_dev)
        if dev["policy"] != policy:
            test.fail(
                "memdev = %s: 'policy' is '%s', but not '%s'!"
                % (mem_dev, dev["policy"], policy)
            )
        prealloc = memdev_params["prealloc"] == "yes"
        if dev["prealloc"] != prealloc:
            test.fail(
                "memdev = %s: 'prealloc' is not '%s'!"
                % (mem_dev, memdev_params["prealloc"])
            )
        if policy == "default":
            continue
        host_node = str(dev["host-nodes"][0])
        if host_node != memdev_params["host-nodes"]:
            test.fail(
                "memdev = %s: 'host-nodes' is '%s', but not '%s'!"
                % (mem_dev, host_node, memdev_params["host-nodes"])
            )


def check_memory_in_procfs(test, params, vm):
    """
    Check memory info in procfs

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    """
    qemu_pid = vm.get_pid()
    policy = params["policy_mem"]
    if policy == "preferred":
        policy = "prefer"
    for mem_dev in params["mem_devs"].split():
        memdev_params = params.object_params(mem_dev)
        mem_size = memdev_params["size"]
        mem_size = int(float(utils_misc.normalize_data_size(mem_size, "K")))
        smaps = process.system_output(
            r"grep -B1 -E '^Size:\s+%d' /proc/%d/smaps" % (mem_size, qemu_pid)
        )
        smaps = astring.to_text(smaps).strip()
        mem_path = memdev_params.get("mem-path")
        if mem_path and (mem_path not in smaps):
            test.fail(
                "memdev = %s: mem-path '%s' is not in smaps '%s'!"
                % (mem_dev, mem_path, smaps)
            )
        mem_start = re.findall("^([0-9a-fA-F]+)-", smaps, re.M)[0]
        numa_maps = process.system_output(
            "grep %s /proc/%d/numa_maps" % (mem_start, qemu_pid)
        )
        numa_maps = astring.to_text(numa_maps).strip()
        if mem_path and (mem_path not in numa_maps):
            test.fail(
                "memdev = %s: mem-path '%s' is not in numa_maps '%s'!"
                % (mem_dev, mem_path, numa_maps)
            )
        numa_maps = re.sub(r"\s+\(many\)", "", numa_maps)
        policy_numa = numa_maps.split()[1].split(":")
        if policy != policy_numa[0]:
            test.fail(
                "memdev = %s:"
                " 'policy' in numa_maps is '%s', but not '%s'!"
                % (mem_dev, policy_numa[0], policy)
            )
        elif policy != "default":
            host_node = memdev_params["host-nodes"]
            if policy_numa[1] != host_node:
                test.fail(
                    "memdev = %s:"
                    " 'host-nodes' in numa_maps is '%s', but not '%s'!"
                    % (mem_dev, policy_numa[1], host_node)
                )


@error_context.context_aware
def run(test, params, env):
    """
    [Memory][Numa] NUMA memdev option, this case will:
    1) Check host's numa node(s).
    2) Start the VM.
    3) Check query-memdev.
    4) Check the memory in procfs.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error_context.context("Check host's numa node(s)!", test.log.info)
    valid_nodes = get_host_numa_node()
    if len(valid_nodes) < 2:
        test.cancel(
            "The host numa nodes that whose size is not zero should be "
            "at least 2! But there is %d." % len(valid_nodes)
        )
    node1 = valid_nodes[0]
    node2 = valid_nodes[1]

    if params.get("policy_mem") != "default":
        error_context.context("Assign host's numa node(s)!", test.log.info)
        params["host-nodes_mem0"] = node1
        params["host-nodes_mem1"] = node2

    if params.get("set_node_hugepage") == "yes":
        hugepage_size = utils_memory.get_huge_page_size()
        normalize_total_hg1 = int(normalize_data_size(params["size_mem0"], "K"))
        hugepage_num1 = normalize_total_hg1 // hugepage_size
        if "numa_hugepage" in params["shortname"]:
            params["target_nodes"] = "%s %s" % (node1, node2)
            normalize_total_hg2 = int(normalize_data_size(params["size_mem1"], "K"))
            hugepage_num2 = normalize_total_hg2 // hugepage_size
            params["target_num_node%s" % node2] = hugepage_num2
        else:
            params["target_nodes"] = node1
        params["target_num_node%s" % node1] = hugepage_num1
        params["setup_hugepages"] = "yes"
        env_process.preprocess(test, params, env)

    error_context.context("Starting VM!", test.log.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Check query-memdev!", test.log.info)
    check_query_memdev(test, params, vm)

    error_context.context("Check the memory in procfs!", test.log.info)
    check_memory_in_procfs(test, params, vm)
    vm.verify_dmesg()
