import math

from avocado.utils import process
from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Boots VMs until one of them becomes unresponsive, and records the maximum
    number of VMs successfully started:
    1) boot the first vm
    2) boot the second vm cloned from the first vm, check whether it boots up
       and all booted vms respond to shell commands
    3) go on until cannot create VM anymore or cannot allocate memory for VM

    :param test:   kvm test object
    :param params: Dictionary with the test parameters
    :param env:    Dictionary with test environment.
    """
    error_context.base_context("waiting for the first guest to be up", test.log.info)

    host_cpu_cnt_cmd = params.get("host_cpu_cnt_cmd")
    host_cpu_num = int(process.getoutput(host_cpu_cnt_cmd).strip())
    if host_cpu_num <= int(params.get("max_vms")):
        test.cancel("No enough physical cpus to pin all guests")
    vm_cpu_num = host_cpu_num // int(params.get("max_vms"))
    if vm_cpu_num == 1:
        params["vcpu_sockets"] = 1
        params["vcpu_threads"] = 1
        params["vcpu_cores"] = 1
    else:
        vm_cpu_num = int(math.floor(float(vm_cpu_num) / 2) * 2)

    host_mem_size_cmd = params.get("host_mem_size_cmd")
    host_mem_size = int(process.getoutput(host_mem_size_cmd).strip())
    vm_mem_size = host_mem_size // int(params.get("max_vms"))

    params["vcpu_maxcpus"] = vm_cpu_num
    params["mem"] = vm_mem_size

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    vm.verify_alive()
    login_timeout = float(params.get("login_timeout", 420))
    session = vm.wait_for_login(timeout=login_timeout)

    num = 2
    sessions = [session]

    # Boot the VMs
    try:
        try:
            while num <= int(params.get("max_vms")):
                # Clone vm according to the first one
                error_context.base_context("booting guest #%d" % num, test.log.info)
                vm_name = "vm%d" % num
                vm_params = vm.params.copy()
                curr_vm = vm.clone(vm_name, vm_params)
                env.register_vm(vm_name, curr_vm)
                env_process.preprocess_vm(test, vm_params, env, vm_name)
                params["vms"] += " " + vm_name

                session = curr_vm.wait_for_login(timeout=login_timeout)
                sessions.append(session)
                test.log.info("Guest #%d booted up successfully", num)

                # Check whether all previous shell sessions are responsive
                for i, se in enumerate(sessions):
                    error_context.context(
                        "checking responsiveness of guest" " #%d" % (i + 1),
                        test.log.debug,
                    )
                    se.cmd(params.get("alive_test_cmd"))
                num += 1
        except Exception as emsg:
            test.fail(
                "Expect to boot up %s guests."
                "Failed to boot up #%d guest with "
                "error: %s." % (params["max_vms"], num, emsg)
            )
    finally:
        for se in sessions:
            se.close()
        test.log.info("Total number booted: %d", (num - 1))
