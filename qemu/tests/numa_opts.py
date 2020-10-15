import logging

from virttest import error_context
from virttest.utils_misc import normalize_data_size
from virttest.utils_misc import get_mem_info
from virttest.utils_misc import NumaInfo


@error_context.context_aware
def run(test, params, env):
    """
    Simple test to check if NUMA options are being parsed properly
    1) Boot vm with different numa nodes
    2) With qemu monitor, check if size and cpus for every node match with cli
    3) In guest os, check if size and cpus for every node match with cli

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def numa_info_guest():
        """
        The numa info in guest os, linux only

        return: An array of (ram, cpus) tuples, where ram is the RAM size in
                MB and cpus is a set of CPU numbers
        """

        numa_info_guest = NumaInfo(session=session)

        numa_guest = []
        nodes_guest = numa_info_guest.online_nodes
        for node in nodes_guest:
            node_size = numa_info_guest.online_nodes_meminfo[node]['MemTotal']
            node_size = float(normalize_data_size('%s KB' % node_size))
            node_cpus = numa_info_guest.online_nodes_cpus[node]
            node_cpus = set([int(v) for v in node_cpus.split()])
            numa_guest.append((node_size, node_cpus))

        # It is a known WONTFIX issue for x86, node info of node0 and node1 is
        # opposite in guest os when vm have 2 nodes
        if (vm_arch in ("x86_64", "i686") and len(numa_guest) == 2):
            numa_guest.reverse()
        return numa_guest

    vm = env.get_vm(params["main_vm"])
    os_type = params["os_type"]
    vm_arch = params["vm_arch_name"]
    session = vm.wait_for_login()

    error_context.context("starting numa_opts test...", logging.info)

    # Get numa info from monitor
    numa_monitor = vm.monitors[0].info_numa()
    error_context.context("numa info in monitor: %r" % numa_monitor, logging.info)
    monitor_expect_nodes = params.get_numeric("monitor_expect_nodes")
    if len(numa_monitor) != monitor_expect_nodes:
        test.fail("[Monitor]Wrong number of numa nodes: %d. Expected: %d" %
                  (len(numa_monitor), monitor_expect_nodes))

    if os_type == 'linux':
        # Get numa info in guest os, only for Linux
        numa_guest = numa_info_guest()
        error_context.context("numa info in guest: %r" % numa_guest, logging.info)
        guest_expect_nodes = int(params.get("guest_expect_nodes",
                                            monitor_expect_nodes))
        if len(numa_guest) != guest_expect_nodes:
            test.fail("[Guest]Wrong number of numa nodes: %d. Expected: %d" %
                      (len(numa_guest), guest_expect_nodes))
        # Use 30 plus the gap of 'MemTotal' in OS and '-m' in cli as threshold
        MemTotal = get_mem_info(session, 'MemTotal')
        MemTotal = float(normalize_data_size('%s KB' % MemTotal))
        error_context.context("MemTotal in guest os is %s MB"
                              % MemTotal, logging.info)
        threshold = float(params.get_numeric("mem") - MemTotal) + 30
        error_context.context("The acceptable threshold is: %s"
                              % threshold, logging.info)
    else:
        numa_guest = numa_monitor
    session.close()

    for nodenr, node in enumerate(numa_guest):
        mdev = params.get("numa_memdev_node%d" % (nodenr))
        if mdev:
            mdev = mdev.split('-')[1]
            size = float(normalize_data_size(params.get("size_%s" % mdev)))
        else:
            size = params.get_numeric("mem")

        numa_cpus = params.get("numa_cpus_node%d" % (nodenr))
        if numa_cpus is not None:
            cpus = []
            for v in numa_cpus.split(","):
                v = v.split('-')
                cpus += [cpuid for cpuid in range(int(v[0]), int(v[-1]) + 1)]
            cpus = set(cpus)
        else:
            cpus = set([int(v) for v in range(params.get_numeric('smp'))])

        if len(numa_monitor) != 0:
            if size != numa_monitor[nodenr][0]:
                test.fail("[Monitor]Wrong size of numa node %d: %f. Expected: %f"
                          % (nodenr, numa_monitor[nodenr][0], size))
            if cpus != numa_monitor[nodenr][1]:
                test.fail("[Monitor]Wrong CPU set on numa node %d: %s. Expected: %s"
                          % (nodenr, numa_monitor[nodenr][1], cpus))

        if os_type == 'linux':
            if size - numa_guest[nodenr][0] > threshold:
                test.fail("[Guest]Wrong size of numa node %d: %f. Expected: %f"
                          % (nodenr, numa_guest[nodenr][0], size))
            if cpus != numa_guest[nodenr][1]:
                test.fail("[Guest]Wrong CPU set on numa node %d: %s. Expected: %s"
                          % (nodenr, numa_guest[nodenr][1], cpus))
