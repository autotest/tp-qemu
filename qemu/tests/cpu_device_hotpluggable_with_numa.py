import re

from virttest import error_context, utils_misc, utils_package

from provider import cpu_utils, win_wora


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug vcpu devices with specified numa nodes.

    1) Boot up guest without vcpu device and with multi numa nodes.
    2) Hotplug vcpu devices and check successfully or not. (qemu side)
    3) Check if the number of CPUs in guest changes accordingly. (guest side)
    4) Check numa info in guest
    5) Hotunplug vcpu devices
    6) Recheck the numa info in guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def assign_numa_cpus(nodes, count):
        """Average allocation of cpu to each node."""
        cpus = list(map(str, range(maxcpus)))
        avg_count = maxcpus / float(len(nodes))
        if avg_count % count != 0:
            avg_count = round(avg_count / count) * count
        numa_cpus_list = []

        last = 0.0
        while last < maxcpus:
            numa_cpus_list.append(cpus[int(last) : int(last + avg_count)])
            last += avg_count
        return dict(zip(nodes, numa_cpus_list))

    def get_guest_numa_cpus_info():
        """Get guest numa information via numactl"""
        # Skip this step on windows guest
        if os_type == "windows":
            return
        numa_out = session.cmd_output("numactl -H | grep cpus")
        numa_cpus_info = re.findall(r"^node (\d+) cpus:([\d| ]*)$", numa_out, re.M)
        return dict(map(lambda x: (x[0], x[1].split()), numa_cpus_info))

    os_type = params["os_type"]
    machine = params["machine_type"]
    login_timeout = params.get_numeric("login_timeout", 360)
    vm = env.get_vm(params["main_vm"])
    maxcpus = vm.cpuinfo.maxcpus
    alignment = vm.cpuinfo.threads if machine.startswith("pseries") else 1
    if not params.objects("vcpu_devices"):
        vcpus_count = vm.cpuinfo.threads if machine.startswith("pseries") else 1
        pluggable_cpus = vm.cpuinfo.maxcpus // vcpus_count // 2
        params["vcpu_devices"] = " ".join(
            ["vcpu%d" % (count + 1) for count in range(pluggable_cpus)]
        )
        vm.destroy()
        if len(params.objects("vcpu_devices")) < 2:
            test.cancel("Insufficient maxcpus for multi-CPU hotplug")
        params["paused_after_start_vm"] = "no"

    error_context.base_context("Define the cpu list for each numa node", test.log.info)
    numa_nodes = params.objects("guest_numa_nodes")
    node_ids = [params["numa_nodeid_%s" % node] for node in numa_nodes]
    node_cpus_mapping = assign_numa_cpus(node_ids, alignment)
    for node in numa_nodes:
        params["numa_cpus_%s" % node] = ",".join(
            node_cpus_mapping[params["numa_nodeid_%s" % node]]
        )

    error_context.context("Launch the guest with our assigned numa node", test.log.info)
    vcpu_devices = params.objects("vcpu_devices")
    vm.create(params=params)
    if vm.is_paused():
        vm.resume()
    session = vm.wait_for_login(timeout=login_timeout)

    if params.get_boolean("workaround_need"):
        win_wora.modify_driver(params, session)

    error_context.context("Check the number of guest CPUs after startup", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.error(
            "The number of guest CPUs is not equal to the qemu command "
            "line configuration"
        )

    if os_type == "linux" and not utils_package.package_install("numactl", session):
        test.cancel("Please install numactl to proceed")
    numa_before_plug = get_guest_numa_cpus_info()
    for vcpu_dev in vcpu_devices:
        error_context.context("hotplug vcpu device: %s" % vcpu_dev, test.log.info)
        vm.hotplug_vcpu_device(vcpu_dev)
    if not utils_misc.wait_for(lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm), 10):
        test.fail("Actual number of guest CPUs is not equal to expected")

    if os_type == "linux":
        error_context.context(
            "Check the CPU information of each numa node", test.log.info
        )
        guest_numa_cpus = get_guest_numa_cpus_info()
        for node_id, node_cpus in node_cpus_mapping.items():
            try:
                if guest_numa_cpus[node_id] != node_cpus:
                    test.log.debug(
                        "Current guest numa info:\n%s", session.cmd_output("numactl -H")
                    )
                    test.fail(
                        "The cpu obtained by guest is inconsistent with " "we assigned."
                    )
            except KeyError:
                test.error("Could not find node %s in guest." % node_id)
        test.log.info("Number of each CPU in guest matches what we assign.")

        for vcpu_dev in vcpu_devices[::-1]:
            error_context.context("hotunplug vcpu device: %s" % vcpu_dev, test.log.info)
            vm.hotunplug_vcpu_device(vcpu_dev)
        if not utils_misc.wait_for(
            lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm), 10
        ):
            test.fail("Actual number of guest CPUs is not equal to expected")
        if get_guest_numa_cpus_info() != numa_before_plug:
            test.log.debug(
                "Current guest numa info:\n%s", session.cmd_output("numactl -H")
            )
            test.fail("Numa info of guest is incorrect after vcpu hotunplug.")
