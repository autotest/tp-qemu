import random
import re

from avocado.utils import cpu
from virttest import env_process, error_context

from provider.cpu_utils import check_if_vm_vcpu_topology_match


@error_context.context_aware
def run(test, params, env):
    """
    Check guest gets correct vcpu num, cpu cores, processors, sockets, siblings

    1) Boot guest with options: -smp n,cores=x,threads=y,sockets=z...
    2) Check cpu topology

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def check(p_name, exp, check_cmd):
        """
        Check the cpu property inside guest
        :param p_name: Property name
        :param exp: The expect value
        :param check_cmd: The param to get check command
        """
        res = session.cmd_output(check_cmd).strip()
        if int(res) != int(exp):
            test.fail(
                "The vcpu %s number inside guest is %s,"
                " while it is set to %s" % (p_name, res, exp)
            )

    vm_name = params["main_vm"]
    os_type = params["os_type"]
    vcpu_threads_list = [1, 2]
    if params["machine_type"] == "pseries":
        vcpu_threads_list = [1, 2, 4, 8]
    if "arm64" in params["machine_type"] or "s390" in params["machine_type"]:
        vcpu_threads_list = [1]
    host_cpu = cpu.online_count()
    params["vcpu_cores"] = vcpu_cores = random.randint(1, min(6, host_cpu // 2))
    for vcpu_threads in vcpu_threads_list:
        vcpu_sockets = min(
            max(host_cpu // (vcpu_cores * vcpu_threads), 1), random.randint(1, 6)
        )
        vcpu_sockets = (
            2 if (os_type == "windows" and vcpu_sockets > 2) else vcpu_sockets
        )
        params["vcpu_sockets"] = vcpu_sockets
        params["vcpu_threads"] = vcpu_threads
        params["smp"] = params["vcpu_maxcpus"] = (
            vcpu_cores * vcpu_threads * vcpu_sockets
        )
        params["start_vm"] = "yes"
        try:
            env_process.preprocess_vm(test, params, env, vm_name)
        except Exception as e:
            # The cpu topology sometimes will be changed by
            # qemu_vm.VM.make_create_command, and thus cause qemu vm fail to
            # start, which is expected; Modify the value and restart vm in
            # this case, and verify cpu topology inside guest after that
            if "qemu-kvm: cpu topology" in str(e):
                sockets = int(re.findall(r"sockets\s+\((\d)\)", str(e))[0])
                threads = int(re.findall(r"threads\s+\((\d)\)", str(e))[0])
                cores = int(re.findall(r"cores\s+\((\d)\)", str(e))[0])
                params["smp"] = params["vcpu_maxcpus"] = sockets * threads * cores
                env_process.preprocess_vm(test, params, env, vm_name)
            else:
                raise
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login()
        if not check_if_vm_vcpu_topology_match(
            session, os_type, vm.cpuinfo, test, vm.devices
        ):
            test.fail("CPU topology of guest is incorrect.")
        if params.get("check_siblings_cmd"):
            check("sibling", vcpu_threads * vcpu_cores, params["check_siblings_cmd"])
        if params.get("check_core_id_cmd"):
            for cpu_id in list(range(params["smp"])):
                check("core_id", cpu_id, params["check_core_id_cmd"] % cpu_id)
        vm.destroy()
