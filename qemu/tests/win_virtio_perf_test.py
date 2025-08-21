from virttest import data_dir, env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Please make sure the guest installed with signed driver
    Verify Secure MOR control feature using Device Guard tool in Windows guest:

    1) Boot up a guest.
    2) Check if Secure Boot is enable.
    3) Download DG_Readiness_Tool and copy to guest.
    4) Enable Device Guard and check the output.
    5) Reboot guest.
    6) Check the result of Device Guard.
    7) Disable Device Guard and shutdown guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def set_powershell_execute_policy():
        """
        Set PowerShell execution policy using the provided session.
        It is used when creating a new session.

        :param cmd: The PowerShell command to set execution policy.
        """
        error_context.context("Setting PowerShell execution policy.")
        status, output = session.cmd_status_output(executionPolicy_command)
        if status != 0:
            test.fail("Failed to set PowerShell execution policy: %s" % output)

    def check_secure_boot_enabled():
        """
        Checks if Secure Boot is enabled in the guest.
        """
        error_context.context("Checking if Secure Boot is enabled in the guest")
        output = session.cmd_output(check_cmd)
        if "false" in output.lower():
            test.fail("Secure Boot is not enabled: %s" % output)

    def copy_dg_readiness_tool():
        """
        Copies the Device Guard Readiness tool from the host to the guest VM.
        """
        dgreadiness_host_path = data_dir.get_deps_dir("dgreadiness")
        dst_path = params["dst_path"]
        test.log.info("Copy Device Guard tool to guest.")
        s, o = session.cmd_status_output("mkdir %s" % dst_path)
        if s and "already exists" not in o:
            test.error(
                "Could not create Device Guard directory in "
                "VM '%s', detail: '%s'" % (vm.name, o)
            )
        vm.copy_files_to(dgreadiness_host_path, dst_path)

    def check_vbs_ready():
        """
        Check the status of Virtualization-Based Security (VBS) using the provided
        session.

        :return: True if VBS is enabled, False otherwise.
        """
        status, output = session.cmd_status_output(ready_command)
        if status != 0:
            test.fail("Failed to check VBS status: %s" % output)
        if vbs_ready_info in output:
            test.log.info("VBS is already enabled, and guest boot up successfully")
            return True
        else:
            test.log.info(
                "VBS is not enabled or the expected info was not found in the output"
            )
            return False

    def run_device_guard_tool(cmd, expect_info):
        """
        Executes the Device Guard Readiness Tool command in the guest to enable
        or disable Virtualization-Based Security (VBS).

        :param cmd: The command to enable or disable VBS.
        """
        error_context.context("running device guard readiness tool with %s" % cmd)
        output = session.cmd_output(cmd, 360)
        if expect_info not in output:
            test.fail("Failed to enable VBS: %s" % output)

    login_timeout = int(params.get("login_timeout", 360))
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"
    params["clone_master"] = "yes"
    params["master_images_clone"] = "image1"
    params["remove_image_image1"] = "yes"
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_serial_login(timeout=login_timeout)

    check_cmd = params["check_secure_boot_enabled_cmd"]
    dgreadiness_path_command = params["dgreadiness_path_cmd"]
    executionPolicy_command = params["set_ps_policy_cmd"]
    enable_command = params["vbs_enable_cmd"]
    disable_command = params["vbs_disable_cmd"]
    ready_command = params["vbs_ready_cmd"]
    vbs_ready_info = params["vbs_ready_info"]
    vbs_enable_info = params["vbs_enable_info"]
    vbs_disable_info = params["vbs_disable_info"]

    try:
        check_secure_boot_enabled()
        copy_dg_readiness_tool()
        set_powershell_execute_policy()
        session.cmd(dgreadiness_path_command)
        if not check_vbs_ready():
            run_device_guard_tool(enable_command, vbs_enable_info)
            vm.reboot(timeout=login_timeout)
            session = vm.wait_for_serial_login(timeout=login_timeout)
            session.cmd(dgreadiness_path_command)
            set_powershell_execute_policy()
            if not check_vbs_ready():
                test.fail("VBS is not enabled after reboot.")
        test.log.info("------------disable -------------")
        run_device_guard_tool(disable_command, vbs_disable_info)
    except Exception as e:
        test.fail(f"Test failed: {e}")
    else:
        test.log.info("Test completed successfully.")
    finally:
        if vm.is_alive():
            vm.destroy()
        if session:
            session.close()
