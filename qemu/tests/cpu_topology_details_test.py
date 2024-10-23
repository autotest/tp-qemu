from virttest import error_context

from provider.cpu_utils import check_if_vm_vcpu_topology_match


def check(session, p_name, exp, check_cmd, test):
    """
    Check the cpu property inside guest
    :param p_name: Property name
    :param exp: The expect value
    :param check_cmd: The param to get check command
    :param test: QEMU test object.
    """
    res = session.cmd_output(check_cmd).strip()
    if int(res) != int(exp):
        test.fail(
            "The vcpu %s number inside guest is %s,"
            " while it is set to %s" % (p_name, res, exp)
        )


def check_details(vm_session, vm_params, vm_cpuinfo, test):
    """
    Run cmds to check more details about the topology.
    Only run these if they are defined in order to handle
    several scenarios

    """
    if vm_params.get("check_sockets_cmd"):
        check(
            vm_session,
            "sockets",
            vm_cpuinfo.sockets,
            vm_params["check_sockets_cmd"],
            test,
        )
    if vm_params.get("check_core_id_cmd"):
        for cpu_id in list(range(vm_cpuinfo.maxcpus)):
            check(
                vm_session,
                "core_id",
                cpu_id,
                vm_params["check_core_id_cmd"] % cpu_id,
                test,
            )
    if vm_params.get("check_core_per_socket_cmd"):
        vm_cores = vm_cpuinfo.cores
        socket_list = vm_session.cmd_output(
            vm_params.get("check_core_per_socket_cmd")
        ).splitlines()
        uni_socket = set(socket_list)
        if len(uni_socket) != vm_cpuinfo.sockets:
            test.fail(
                "The number of socket is not expected, expect:%s, "
                "actual:%s" % (vm_cpuinfo.sockets, len(uni_socket))
            )
        for value in uni_socket:
            if socket_list.count(value) != vm_cores:
                test.fail(
                    "The number of cores per socket is not expected, "
                    "expect:%s, actual:%s" % (vm_cores, len(socket_list.count(value)))
                )


@error_context.context_aware
def run(test, params, env):
    """
    Check guest gets correct vcpu num, cpu cores, processors, sockets, siblings

    1) Boot guest with options: -smp n,cores=x,threads=y,sockets=z...
    2) Check cpu topology is expected as set up
    3) Check if socket number is expected
    4) Check if cores per socket is expected

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm_name = params["main_vm"]
    os_type = params["os_type"]
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()
    if not check_if_vm_vcpu_topology_match(
        session, os_type, vm.cpuinfo, test, vm.devices
    ):
        test.fail("CPU topology of guest is incorrect.")
    check_details(session, params, vm.cpuinfo, test)
    vm.destroy()
