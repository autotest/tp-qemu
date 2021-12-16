from virttest import env_process


def run(test, params, env):
    """
    Test steps:
    1) Check whether the host memory is greater than boot guest memory:
    If the host memory is greater than boot guest memory,
    continue to test the case,Otherwise, skip the test case
    2) Boot guest with max memory and two cpus
    3) Check guest dmesg, no call trace message

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    guest_dmesg_cmd = params.get("guest_dmesg_cmd")
    check_guest_dmesg = params.get("check_guest_dmesg")
    status, output = session.cmd_status_output(guest_dmesg_cmd)
    if status == 0 and check_guest_dmesg in output:
        test.log.debug("dmesg log:\n%s", output)
        test.fail("Guest dmesg has Call Trace")
    session.close()
