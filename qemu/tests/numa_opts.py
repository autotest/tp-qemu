import logging


logger = logging.getLogger(__name__)
dbg = logger.debug


def run(test, params, env):
    """
    Simple test to check if NUMA options are being parsed properly

    This _does not_ test if NUMA information is being properly exposed to the
    guest.
    """

    dbg("starting numa_opts test...")

    vm = env.get_vm(params["main_vm"])

    numa = vm.monitors[0].info_numa()
    dbg("info numa reply: %r", numa)

    numa_nodes = params.get("numa_nodes")
    if numa_nodes:
        numa_nodes = int(params.get("numa_nodes"))
        if len(numa) != numa_nodes:
            test.fail(
                "Wrong number of numa nodes: %d. Expected: %d" %
                (len(numa), numa_nodes))

    for nodenr, node in enumerate(numa):
        size = params.get("numa_node%d_size" % (nodenr))
        if size is not None:
            size = int(size)
            if size != numa[nodenr][0]:
                test.fail(
                    "Wrong size of numa node %d: %d. Expected: %d" %
                    (nodenr, numa[nodenr][0], size))

        cpus = params.get("numa_node%d_cpus" % (nodenr))
        if cpus is not None:
            cpus = set([int(v) for v in cpus.split()])
            if cpus != numa[nodenr][1]:
                test.fail(
                    "Wrong CPU set on numa node %d: %s. Expected: %s" %
                    (nodenr, numa[nodenr][1], cpus))
