import re

from avocado.utils import process
from virttest import env_process, error_context
from virttest.utils_misc import NumaInfo, get_mem_info, normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    Bind guest node0 and node1 to 2 host nodes, do migration test

    1. Boot src guest with 2 numa node and all bind to 2 host numa nodes
    2. Migration
    3. Check the numa memory size in guest, linux guest only
    4. Check the numa memory policy in dest host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def get_nodes_size(size_type="MemTotal", session=None):
        """
        Get the node size of each node in host/guest, descending sort with size

        :param size_type: the type of the node size
        :param session: ShellSession object

        :return: a list of tuple include node id and node size(M)
        :rtype: list
        """
        numa_info = NumaInfo(session=session)
        nodes_size = {}
        numa_nodes = numa_info.online_nodes
        for node in numa_nodes:
            node_size = numa_info.online_nodes_meminfo[node][size_type]
            nodes_size[node] = float(normalize_data_size("%s KB" % node_size))
        nodes_size = sorted(nodes_size.items(), key=lambda item: item[1], reverse=True)
        return nodes_size

    host_nodes_size = get_nodes_size(size_type="MemFree")
    mem_devs = params.objects("mem_devs")
    if len(host_nodes_size) < len(mem_devs):
        test.cancel("Host do not have enough nodes for testing!")
    for mem_dev in mem_devs:
        size_mem = params.object_params(mem_dev).get("size_mem")
        size_mem = float(normalize_data_size(size_mem))
        if host_nodes_size[0][1] >= size_mem:
            params["host-nodes_mem_%s" % mem_dev] = str(host_nodes_size[0][0])
            del host_nodes_size[0]
        else:
            test.cancel("host nodes do not have enough memory for testing!")

    params["start_vm"] = "yes"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    # do migration
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    vm.migrate(mig_timeout, mig_protocol, env=env)
    session = vm.wait_for_login()

    os_type = params["os_type"]
    if os_type == "linux":
        error_context.context("Check the numa memory size in guest", test.log.info)
        # Use 30 plus the gap of 'MemTotal' in OS and '-m' in cli as threshold
        mem_total = get_mem_info(session, "MemTotal")
        mem_total = float(normalize_data_size("%s KB" % mem_total))
        error_context.context(
            "MemTotal in guest os is %s MB" % mem_total, test.log.info
        )
        threshold = float(params.get_numeric("mem") - mem_total) + 30
        error_context.context(
            "The acceptable threshold is: %s" % threshold, test.log.info
        )
        guest_nodes_size = get_nodes_size(size_type="MemTotal", session=session)
        guest_nodes_size = dict(guest_nodes_size)
        for nodenr, node in enumerate(params.objects("guest_numa_nodes")):
            mdev = params.get("numa_memdev_node%d" % nodenr)
            if mdev:
                mdev = mdev.split("-")[1]
                size = float(normalize_data_size(params.get("size_mem_%s" % mdev)))
                if abs(size - guest_nodes_size[nodenr]) > threshold:
                    test.fail(
                        "[Guest]Wrong size of numa node %d: %f. Expected:"
                        " %s" % (nodenr, guest_nodes_size[nodenr], size)
                    )

    error_context.context("Check the numa memory policy in dest host", test.log.info)
    qemu_pid = vm.get_pid()
    for mem_dev in mem_devs:
        memdev_params = params.object_params(mem_dev)
        size_mem = memdev_params.get("size_mem")
        size_mem = int(float(normalize_data_size(size_mem, "K")))
        smaps = process.getoutput(
            "grep -E -B1 '^Size: *%d' /proc/%d/smaps" % (size_mem, qemu_pid)
        )
        mem_start_pattern = (
            r"(\w+)-\w+\s+\w+-\w+\s+\w+\s+\w+:\w+\s\w+\s+\n" r"Size:\s+%d" % size_mem
        )
        match = re.search(mem_start_pattern, smaps)
        if not match:
            test.error("Failed to get the mem start address in smaps: %s" % smaps)
        mem_start = match.groups()[0]
        numa_maps = process.getoutput(
            "grep %s /proc/%d/numa_maps" % (mem_start, qemu_pid)
        )
        node_match = re.search(r"bind:(\d+)", numa_maps)
        if not node_match:
            test.fail("Failed to get the bind node in numa_maps: %s" % numa_maps)
        bind_node = node_match.groups()[0]
        expected_node = memdev_params.get("host-nodes_mem")
        if bind_node != expected_node:
            test.fail(
                "Host node for memdev %s in numa_maps is %s, while the "
                "expected is:%s" % (mem_dev, bind_node, expected_node)
            )
