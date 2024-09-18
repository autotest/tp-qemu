from virttest import data_dir, env_process


def run(test, params, env):
    """
    Please make sure the guest installed with signed driver
    Verify Secure MOR control feature using Device Guard tool in Windows guest:

    1) Boot up a guest.
    2) Check if Secure Boot is enable.
    3) Download Device Guard and copy to guest.
    4) Enable Device Guard and check the output.
    5) Reboot guest.
    5) Run Device Guard and check the output.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def execute_powershell_command(command, timeout=60):
        status, output = session.cmd_status_output(command, timeout)
        if status != 0:
            test.fail("execute command fail: %s" % output)
        return output

    login_timeout = int(params.get("login_timeout", 360))
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"
    params["cpu_model_flags"] = ",hv-passthrough"
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_serial_login(timeout=login_timeout)

    check_cmd = params["check_secure_boot_enabled_cmd"]
    dgreadiness_path_command = params["dgreadiness_path_command"]
    executionPolicy_command = params["executionPolicy_command"]
    enable_command = params["enable_command"]
    ready_command = params["ready_command"]
    try:
        output = session.cmd_output(check_cmd)
        if "False" in output:
            test.fail("Secure boot is not enabled. The actual output is %s" % output)

        # Copy Device Guard to guest
        dgreadiness_host_path = data_dir.get_deps_dir("dgreadiness")
        dst_path = params["dst_path"]
        test.log.info("Copy Device Guuard to guest.")
        s, o = session.cmd_status_output("mkdir %s" % dst_path)
        if s and "already exists" not in o:
            test.error(
                "Could not create Device Guard directory in "
                "VM '%s', detail: '%s'" % (vm.name, o)
            )
        vm.copy_files_to(dgreadiness_host_path, dst_path)

        execute_powershell_command(dgreadiness_path_command)
        execute_powershell_command(executionPolicy_command)
        output = execute_powershell_command(enable_command)
        check_enable_info = params["check_enable_info"]
        if check_enable_info not in output:
            test.fail("Device Guard enable failed. The actual output is %s" % output)

        # Reboot guest and run Device Guard
        session = vm.reboot(session)
        execute_powershell_command(dgreadiness_path_command)
        execute_powershell_command(executionPolicy_command)
        output = execute_powershell_command(ready_command)
        check_ready_info = params["check_ready_info"]
        if check_ready_info not in output:
            test.fail("Device Guard running failed. The actual output is %s" % output)

    finally:
        session.close()
