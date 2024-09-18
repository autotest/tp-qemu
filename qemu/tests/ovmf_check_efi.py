def run(test, params, env):
    """
    Check if guest boots from uefi

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    os_type = params["os_type"]

    check_cmd = params["check_cmd"]
    efi_info = params["efi_info"]
    dmesg_cmd = params["dmesg_cmd"]
    check_output = session.cmd_output_safe(check_cmd)
    if os_type == "linux":
        dmesg_cmd = params["dmesg_cmd"]
        dmesg_output = session.cmd_output_safe(dmesg_cmd)
        if efi_info not in check_output or not dmesg_output:
            test.fail(
                "No 'EFI System Partition' info in output of 'gdisk -l', "
                "or no efi related info in dmesg"
            )
    if os_type == "windows" and efi_info not in check_output:
        test.fail("BIOS version of guest is %s, it should be UEFI" % check_output)
