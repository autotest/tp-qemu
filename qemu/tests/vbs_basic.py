import threading
import time

from virttest import data_dir, env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test VBS (Virtualization-Based Security) functionality in Windows guest.

    Prerequisites:
        - Guest must have UEFI Secure Boot enabled
        - Signed drivers must be installed

    Test steps:
        1) Boot up a Windows guest with UEFI Secure Boot
        2) Verify Secure Boot is enabled
        3) Copy DG_Readiness_Tool to guest
        4) Enable or disable VBS based on test variant (disable_vbs parameter)
        5) Reboot guest and verify VBS state matches expectation

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def check_secure_boot_enabled():
        """
        Checks if Secure Boot is enabled in the guest.
        """
        error_context.context("Checking if Secure Boot is enabled in the guest")
        check_cmd = params["check_secure_boot_enabled_cmd"]
        output = session.cmd_output(check_cmd)
        if "false" in output.lower():
            test.fail("Secure Boot is not enabled: %s" % output)

    def copy_dg_readiness_tool():
        """
        Copies the Device Guard Readiness tool from the host to the guest VM.
        """
        dgreadiness_host_path = data_dir.get_deps_dir("dgreadiness")
        dst_path = params.get("dst_path", "C:\\")
        test.log.info("Copy Device Guard tool to guest.")
        vm.copy_files_to(dgreadiness_host_path, dst_path)

    def check_vbs_ready():
        """
        Check the status of Virtualization-Based Security (VBS) using the provided
        session.

        :return: True if VBS is enabled, False otherwise.
        """
        vbs_tool_cmd = vbs_tool_ps_prefix + vbs_tool_ps_suffix.format(action="Ready")
        status, output = session.cmd_status_output(vbs_tool_cmd)
        if status != 0:
            test.fail("%s failed with : %s" % (vbs_tool_cmd, output))
        if vbs_ready_info in output:
            test.log.info("VBS is already enabled, and guest boot up successfully")
            return True
        else:
            test.log.info(
                "VBS is not enabled or the expected info was not found in the output"
            )
            return False

    def run_device_guard_tool(action, expect_info):
        """
        Executes the Device Guard Readiness Tool command in the guest to enable
        or disable Virtualization-Based Security (VBS).

        :param action: Action string (e.g., "Enable", "Disable")
        :param expect_info: Expected output string for validation
        """
        error_context.context("running device guard readiness tool with %s" % action)
        vbs_tool_cmd = vbs_tool_ps_prefix + vbs_tool_ps_suffix.format(action=action)
        status, output = session.cmd_status_output(vbs_tool_cmd, timeout=300)
        if status != 0:
            test.fail("%s failed: %s" % (action, output))
        if expect_info in output:
            test.log.info(
                "VBS command '%s' executed successfully with expected info",
                action,
            )
        else:
            test.fail(
                "VBS command %s executed but expected info not found: %s"
                % (action, output)
            )

    def send_opt_out_keys(vm_obj, stop_event):
        """
        Sends the F3 key continuously to confirm VBS disablement during UEFI boot.
        """
        while not stop_event.is_set():
            if vm_obj.is_alive():
                try:
                    vm_obj.send_key("f3")
                except Exception:
                    pass
            time.sleep(2)

    def vbs_reboot():
        """
        Reboots the VM and waits for login.
        """
        nonlocal session
        test.log.info("Rebooting guest...")
        vm.reboot(timeout=login_timeout)
        if session:
            session.close()
        session = vm.wait_for_serial_login(timeout=login_timeout)
        return session

    login_timeout = int(params.get("login_timeout", 720))
    params["ovmf_vars_filename"] = "OVMF_VARS.secboot.fd"

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_serial_login(timeout=login_timeout)
    vbs_tool_ps_prefix = params["vbs_tool_ps_prefix"]
    vbs_tool_ps_suffix = params["vbs_tool_ps_suffix"]
    vbs_ready_info = params["vbs_ready_info"]
    vbs_enable_info = params["vbs_enable_info"]
    vbs_disable_info = params["vbs_disable_info"]
    dg_cmd = params["dg_cmd"]

    try:
        check_secure_boot_enabled()
        copy_dg_readiness_tool()

        enable_vbs = params.get("disable_vbs", "no").lower() == "no"
        vbs_is_ready = check_vbs_ready()

        # Only take action if current state doesn't match desired state
        if enable_vbs and not vbs_is_ready:
            run_device_guard_tool("Enable", vbs_enable_info)
            session = vbs_reboot()

            test.log.info("Device Guard status: %s", session.cmd_output(dg_cmd))
            if not check_vbs_ready():
                test.fail("VBS is not enabled after reboot.")
        elif not enable_vbs and vbs_is_ready:
            run_device_guard_tool("Disable", vbs_disable_info)
            test.log.info(
                "Starting background thread to send F3 key "
                "during reboot to confirm VBS disablement."
            )
            stop_event = threading.Event()
            key_thread = threading.Thread(
                target=send_opt_out_keys, args=(vm, stop_event)
            )
            key_thread.start()
            try:
                vm.reboot(timeout=login_timeout)
            finally:
                stop_event.set()
                key_thread.join()
            session.close()
            session = vm.wait_for_serial_login(timeout=login_timeout)
            if check_vbs_ready():
                test.fail("VBS is still enabled after disable operation.")
        else:
            state = "enabled" if vbs_is_ready else "disabled"
            test.log.info("VBS is already %s, matching desired state.", state)

        test.log.info("Test completed successfully.")
    finally:
        if session:
            session.close()
        if vm.is_alive():
            vm.destroy()
