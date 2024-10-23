import re

from virttest import error_context, utils_package
from virttest.utils_misc import NumaInfo


@error_context.context_aware
def run(test, params, env):
    """
    Assign cpu to numa node with "-numa cpu", check the numa info in monitor
    and guest os match with the qemu cli
    """

    def convert_cpu_topology_to_ids(
        socketid=None, dieid=None, clusterid=None, coreid=None, threadid=None
    ):
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

        if vm_arch in ("x86_64", "i686"):
            socket_min, socket_max = _get_boundary(
                socketid, vcpu_sockets, socket_weight
            )
            die_min, die_max = _get_boundary(dieid, vcpu_dies, die_weight)
            core_min, core_max = _get_boundary(coreid, vcpu_cores, core_weight)
            thread_min, thread_max = _get_boundary(
                threadid, vcpu_threads, thread_weight
            )
            cpu_min = socket_min + die_min + core_min + thread_min
            cpu_max = socket_max + die_max + core_max + thread_max
        elif vm_arch in ("ppc64", "ppc64le"):
            cpu_min = int(coreid)
            cpu_max = int(coreid) + vcpu_threads - 1
        elif vm_arch == "aarch64":
            socket_min, socket_max = _get_boundary(
                socketid, vcpu_sockets, socket_weight
            )
            cluster_min, cluster_max = _get_boundary(
                clusterid, vcpu_clusters, cluster_weight
            )
            core_min, core_max = _get_boundary(coreid, vcpu_cores, core_weight)
            thread_min, thread_max = _get_boundary(
                threadid, vcpu_threads, thread_weight
            )
            cpu_min = socket_min + cluster_min + core_min + thread_min
            cpu_max = socket_max + cluster_max + core_max + thread_max
        cpu_list = list(range(cpu_min, cpu_max + 1))  # pylint: disable=E0606
        return cpu_list

    def numa_cpu_guest():
        """
        Get the cpu id list for each node in guest os, sort with node id.
        """
        error_context.context("Get cpus in guest os", test.log.info)
        numa_cpu_guest = []
        if vm_arch in ("ppc64", "ppc64le"):
            numa_info_guest = NumaInfo(session=session)  # pylint: disable=E0606
            nodes_guest = numa_info_guest.online_nodes
            for node in nodes_guest:
                numa_cpus = numa_info_guest.online_nodes_cpus[node]
                numa_cpus = sorted([int(v) for v in numa_cpus.split()])
                numa_cpu_guest.append(numa_cpus)
        else:
            error_context.context("Get SRAT ACPI table", test.log.info)
            if not utils_package.package_install("acpidump", session):
                test.cancel("Please install acpidump in guest to proceed")
            content = session.cmd_output(
                "cd /tmp && acpidump -n SRAT -b && " "iasl -d srat.dat && cat srat.dsl"
            )
            pattern = re.compile(
                r"Proximity Domain Low\(8\)\s+:\s+([0-9A-Fa-f]+)"
                r"\n.*Apic ID\s+:\s+([0-9A-Fa-f]+)"
            )
            if vm_arch == "aarch64":
                pattern = re.compile(
                    r"Proximity Domain\s+:\s+([0-9A-Fa-f]+)"
                    r"\n.*Acpi Processor UID\s+:\s+([0-9A-Fa-f]+)"
                )
            node_cpus = pattern.findall(content)

            tmp = {}
            for item in node_cpus:
                nodeid = int(item[0], 16)
                cpuid = int(item[1], 16)
                if nodeid in tmp.keys():
                    tmp[nodeid] += [cpuid]
                else:
                    tmp[nodeid] = [cpuid]
            for item in sorted(tmp.items(), key=lambda item: item[0]):
                numa_cpu_guest.append(sorted(item[1]))
        return numa_cpu_guest

    def numa_cpu_cli():
        """
        Get the cpu id list for each node according to the qemu cli, sort with nodeid.
        """
        error_context.context(
            "Get the expected cpus in qemu command line", test.log.info
        )
        numa_cpus = params.objects("guest_numa_cpus")
        numa_cpu_cli = []
        tmp = {}
        for numa_cpu in numa_cpus:
            numa_cpu_params = params.object_params(numa_cpu)
            nodeid = numa_cpu_params["numa_cpu_nodeid"]
            socket = numa_cpu_params.get("numa_cpu_socketid")
            die = numa_cpu_params.get("numa_cpu_dieid")
            cluster = numa_cpu_params.get("numa_cpu_clusterid")
            core = numa_cpu_params.get("numa_cpu_coreid")
            thread = numa_cpu_params.get("numa_cpu_threadid")
            cpu_list = convert_cpu_topology_to_ids(socket, die, cluster, core, thread)
            if nodeid in tmp.keys():
                tmp[nodeid] += cpu_list
            else:
                tmp[nodeid] = cpu_list
        for item in sorted(tmp.items(), key=lambda item: item[0]):
            numa_cpu_cli.append(sorted(item[1]))
        return numa_cpu_cli

    def numa_cpu_setted(numa_cpu_options):
        """
        Get the new setted cpu id list for each node according to the set options,
        sort with nodeid.
        """
        numa_cpu_setted = []
        tmp = {}
        for cpu in numa_cpu_options:
            nodeid = cpu["node_id"]
            socket = cpu.get("socket_id")
            die = cpu.get("die_id")
            cluster = cpu.get("cluster_id")
            core = cpu.get("core_id")
            thread = cpu.get("thread_id")
            cpu_list = convert_cpu_topology_to_ids(socket, die, cluster, core, thread)
            if nodeid in tmp.keys():
                tmp[nodeid] += cpu_list
            else:
                tmp[nodeid] = cpu_list
        for item in sorted(tmp.items(), key=lambda item: item[0]):
            numa_cpu_setted.append(sorted(item[1]))
        return numa_cpu_setted

    def get_hotpluggable_cpus():
        """
        Get the specified cpu id list for each node that sort with node id and
        unspecified cpu topology with the output of "query-hotpluggable-cpus".
        """
        error_context.context("Get the hotpluggable cpus", test.log.info)
        specified_cpus = []
        unspecified_cpus = []
        tmp = {}
        out = vm.monitor.info("hotpluggable-cpus")
        for vcpu_info in out:
            vcpu_info["vcpus-count"]
            vcpu_info = vcpu_info["props"]
            nodeid = vcpu_info.get("node-id")
            socket = vcpu_info.get("socket-id")
            die = vcpu_info.get("die-id")
            cluster = vcpu_info.get("cluster-id")
            core = vcpu_info.get("core-id")
            thread = vcpu_info.get("thread-id")
            if nodeid is not None:
                cpu_list = convert_cpu_topology_to_ids(
                    socket, die, cluster, core, thread
                )
                if nodeid in tmp.keys():
                    tmp[nodeid] += cpu_list
                else:
                    tmp[nodeid] = cpu_list
            else:
                options = {
                    "socket_id": socket,
                    "die_id": die,
                    "cluster_id": cluster,
                    "core_id": core,
                    "thread_id": thread,
                }
                for key in list(options.keys()):
                    if options[key] is None:
                        del options[key]
                unspecified_cpus.append(options)

        for item in sorted(tmp.items(), key=lambda item: item[0]):
            specified_cpus.append(sorted(item[1]))
        return specified_cpus, unspecified_cpus

    vm = env.get_vm(params["main_vm"])
    qemu_preconfig = params.get_boolean("qemu_preconfig")
    os_type = params["os_type"]
    vm_arch = params["vm_arch_name"]

    vcpu_threads = params.get_numeric("vcpu_threads")
    if vm_arch in ("x86_64", "i686"):
        vcpu_sockets = params.get_numeric("vcpu_sockets")
        vcpu_dies = params.get_numeric("vcpu_dies")
        vcpu_cores = params.get_numeric("vcpu_cores")

        socket_weight = vcpu_dies * vcpu_cores * vcpu_threads
        die_weight = vcpu_cores * vcpu_threads
        core_weight = vcpu_threads
        thread_weight = 1

    if vm_arch == "aarch64":
        vcpu_sockets = params.get_numeric("vcpu_sockets")
        vcpu_clusters = params.get_numeric("vcpu_clusters")
        vcpu_cores = params.get_numeric("vcpu_cores")

        socket_weight = vcpu_clusters * vcpu_cores * vcpu_threads
        cluster_weight = vcpu_cores * vcpu_threads
        core_weight = vcpu_threads
        thread_weight = 1

    numa_cpu_cli = numa_cpu_cli()

    if vm_arch != "aarch64":
        specified_cpus, unspecified_cpus = get_hotpluggable_cpus()

        if specified_cpus != numa_cpu_cli:
            test.fail(
                "cpu ids for each node with 'info hotpluggable-cpus' is: %s,"
                "but the seting in qemu cli is: %s" % (specified_cpus, numa_cpu_cli)
            )

    if qemu_preconfig:
        node_ids = []
        for node in params.objects("guest_numa_nodes"):
            node_params = params.object_params(node)
            node_ids.append(node_params.get_numeric("numa_nodeid"))
        node_ids = sorted(node_ids)

        # Set unspecified cpus from node 0 to max, and set the left cpus to node 0
        set_numa_node_options = []
        for index, cpu_option in enumerate(unspecified_cpus):  # pylint: disable=E0606
            try:
                cpu_option.update({"node_id": node_ids[index]})
            except IndexError:
                cpu_option.update({"node_id": 0})
            set_numa_node_options.append(cpu_option)

        for options in set_numa_node_options:
            vm.monitor.set_numa_node("cpu", **options)

        numa_cpu_setted = numa_cpu_setted(set_numa_node_options)

        expected_cpus = []
        # All nodes have corresponding cpus in qemu cli at the initial state
        numa_cpu_setted.extend([[]] * (len(numa_cpu_cli) - len(numa_cpu_setted)))
        for item in zip(numa_cpu_cli, numa_cpu_setted):
            expected_cpus.append(sorted(item[0] + item[1]))

        if vm_arch != "aarch64":
            new_specified_cpus = get_hotpluggable_cpus()[0]
            if new_specified_cpus != expected_cpus:
                test.fail(
                    "cpu ids for each node with 'info hotpluggable-cpus' after"
                    "numa_cpu_set is %s, but expected result is: %s"
                    % (new_specified_cpus, expected_cpus)
                )

        vm.monitor.exit_preconfig()
        vm.resume()
    else:
        expected_cpus = numa_cpu_cli

    numa_cpu_monitor = [sorted(list(item[1])) for item in vm.monitor.info_numa()]
    if numa_cpu_monitor != expected_cpus:
        test.fail(
            "cpu ids for each node with 'info numa' after setted is: %s, "
            "but expected result is: %s" % (numa_cpu_monitor, expected_cpus)
        )

    # check numa cpus in guest os, only for Linux
    if os_type == "linux":
        session = vm.wait_for_login()
        numa_cpu_guest = numa_cpu_guest()
        session.close()
        if numa_cpu_guest != expected_cpus:
            test.fail(
                "cpu ids for each node in guest os is: %s, but the "
                "expected result is: %s" % (numa_cpu_guest, expected_cpus)
            )
