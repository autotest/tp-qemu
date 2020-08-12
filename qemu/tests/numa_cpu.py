import logging

from virttest import error_context
from virttest.utils_misc import NumaInfo


@error_context.context_aware
def run(test, params, env):
    """
    Assign cpu to numa node with "-numa cpu", check the numa info in monitor
    and guest os match with the qemu cli
    """

    def convert_cpu_topology_to_ids(socketid=None, dieid=None, coreid=None,
                                    threadid=None):
        """
        Convert the cpu topology to cpu id list
        """
        def _get_boundary(value, max_value, weight):
            """
            Get the data range of one bit

            :param value: the current value of the bit
            :param max_value: the max value of the bit
            :param weight: the weight of the bit
            """
            min_boundary = int(value if value is not None else 0) * weight
            max_boundary = int(value if value is not None else (max_value - 1)) * weight
            return (min_boundary, max_boundary)

        if vm_arch in ('x86_64', 'i386'):
            socket_min, socket_max = _get_boundary(socketid, vcpu_sockets, socket_weight)
            die_min, die_max = _get_boundary(dieid, vcpu_dies, die_weight)
            core_min, core_max = _get_boundary(coreid, vcpu_cores, core_weight)
            thread_min, thread_max = _get_boundary(threadid, vcpu_threads, thread_weight)
            cpu_min = socket_min + die_min + core_min + thread_min
            cpu_max = socket_max + die_max + core_max + thread_max
        elif vm_arch in ('ppc64', 'ppc64le'):
            cpu_min = int(coreid)
            cpu_max = int(coreid) + vcpu_threads - 1
        cpu_list = list(range(cpu_min, cpu_max + 1))
        return cpu_list

    def numa_cpu_guest():
        """
        Get the cpu id list for each node in guest os, linux only
        """
        error_context.context("Get cpus in guest os", logging.info)
        numa_info_guest = NumaInfo(session=session)
        nodes_guest = numa_info_guest.online_nodes
        numa_cpu_guest = []
        for node in nodes_guest:
            numa_cpus = numa_info_guest.online_nodes_cpus[node]
            numa_cpus = set([int(v) for v in numa_cpus.split()])
            numa_cpu_guest.append(numa_cpus)
        return numa_cpu_guest

    def numa_cpu_cli():
        """
        Get the cpu id list for each node according to the qemu cli
        """
        error_context.context("Get the expected cpus in qemu command line", logging.info)
        numa_cpus = params.objects("guest_numa_cpus")
        numa_cpu_cli = []
        tmp = {}
        for numa_cpu in numa_cpus:
            numa_cpu_params = params.object_params(numa_cpu)
            nodeid = numa_cpu_params["numa_cpu_nodeid"]
            socket = numa_cpu_params.get("numa_cpu_socketid")
            die = numa_cpu_params.get("numa_cpu_dieid")
            core = numa_cpu_params.get("numa_cpu_coreid")
            thread = numa_cpu_params.get("numa_cpu_threadid")
            cpu_list = convert_cpu_topology_to_ids(socket, die, core, thread)
            if nodeid in tmp.keys():
                tmp[nodeid] += cpu_list
            else:
                tmp[nodeid] = cpu_list
        for item in sorted(tmp.items(), key=lambda item: item[0]):
            numa_cpu_cli.append(set(sorted(item[1])))
        return numa_cpu_cli

    def get_hotpluggable_cpus():
        """
        Get the cpu id list for each node with the output of "query-hotpluggable-cpus"
        """
        error_context.context("Get the hotpluggable cpus", logging.info)
        specified_cpus = []
        tmp = {}
        out = vm.monitor.info("hotpluggable-cpus")
        for vcpu_info in out:
            vcpus_count = vcpu_info["vcpus-count"]
            vcpu_info = vcpu_info["props"]
            nodeid = vcpu_info.get("node-id")
            socket = vcpu_info.get("socket-id")
            die = vcpu_info.get("die-id")
            core = vcpu_info.get("core-id")
            thread = vcpu_info.get("thread-id")
            if nodeid is not None:
                cpu_list = convert_cpu_topology_to_ids(socket, die, core, thread)
                if nodeid in tmp.keys():
                    tmp[nodeid] += cpu_list
                else:
                    tmp[nodeid] = cpu_list
        for item in sorted(tmp.items(), key=lambda item: item[0]):
            specified_cpus.append(set(sorted(item[1])))
        return specified_cpus

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    os_type = params["os_type"]
    vm_arch = params["vm_arch_name"]

    vcpu_threads = params.get_numeric('vcpu_threads')
    if vm_arch in ('x86_64', 'i386'):
        vcpu_sockets = params.get_numeric('vcpu_sockets')
        vcpu_dies = params.get_numeric('vcpu_dies')
        vcpu_cores = params.get_numeric('vcpu_cores')

        socket_weight = vcpu_dies * vcpu_cores * vcpu_threads
        die_weight = vcpu_cores * vcpu_threads
        core_weight = vcpu_threads
        thread_weight = 1

    numa_cpu_cli = numa_cpu_cli()
    specified_cpus = get_hotpluggable_cpus()
    numa_cpu_monitor = [item[1] for item in vm.monitor.info_numa()]

    if specified_cpus != numa_cpu_cli:
        test.fail("cpu ids for each node with 'info hotpluggable-cpus' is: %s,"
                  "but the expected result is: %s" % (specified_cpus, numa_cpu_cli))
    if numa_cpu_monitor != numa_cpu_cli:
        test.fail("cpu ids for each node with 'info numa' is: %s, but the "
                  "expected result is: %s" % (numa_cpu_monitor, numa_cpu_cli))
    if os_type == 'linux':
        # Get numa cpus in guest os, only for Linux
        numa_cpu_guest = numa_cpu_guest()
        if numa_cpu_guest != numa_cpu_cli:
            test.fail("cpu ids for each node in guest os is: %s, but the "
                      "expected result is: %s" % (numa_cpu_guest, numa_cpu_cli))
