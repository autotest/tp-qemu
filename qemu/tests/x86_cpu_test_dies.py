import random

from avocado.utils import cpu
from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check guest gets correct multiple vcpu dies

    1) Boot guest with options: -smp n,dies=2x...
    2) Check cpu dies(only for Linux guest and Intel host)

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm_name = params["main_vm"]
    vcpu_dies_list = [2, 4]
    params["vcpu_dies"] = random.choice(vcpu_dies_list)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()
    if params["os_type"] == "linux" and cpu.get_vendor() == "intel":
        check_die_id = params["check_die_id"]
        check_die_cpus_list = params["check_die_cpus_list"]
        vcpu_sockets = vm.cpuinfo.sockets
        vcpu_dies = vm.cpuinfo.dies
        old_check = params.get("old_check", "no")
        dies_id = session.cmd_output(check_die_id).strip().split("\n")
        dies_cpus_list = session.cmd_output(check_die_cpus_list).strip().split("\n")
        if old_check == "yes":
            dies_check = int(vcpu_dies)
            dies_list_check = int(vcpu_sockets) * int(vcpu_dies)
        else:
            dies_check = dies_list_check = int(vcpu_sockets) * int(vcpu_dies)
        if len(dies_id) != dies_check:
            test.fail("die_id is not right: %d != %d" % (len(dies_id), dies_check))
        if len(dies_cpus_list) != dies_list_check:
            test.fail(
                "die_cpus_list is not right: %d != %d"
                % (len(dies_cpus_list), dies_list_check)
            )

    vm.verify_kernel_crash()
    session.close()
    vm.destroy()
