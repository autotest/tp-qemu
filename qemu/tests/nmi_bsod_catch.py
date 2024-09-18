import time

from virttest import error_context, utils_test

from provider import win_dump_utils


@error_context.context_aware
def run(test, params, env):
    """
    Generate a dump on NMI, then analyse the dump file:
    1) Boot a windows guest.
    2) Check whether driver verifier enabled in guest.
    3) Edit the guest's system registry if need.
    4) Reboot the guest.
    5) Send inject-nmi or nmi from host to guest.
    6) Send a reboot command or a system_reset monitor command (optional)
    7) Verify whether the dump files are generated.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Boot a windows guest", test.log.info)
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    manual_reboot_cmd = params.get("manual_reboot_cmd")
    check_dump_cmd = params.get("check_dump_cmd")
    nmi_cmd = params.get("nmi_cmd")
    del_dump_cmd = params.get("del_dump_cmd")
    driver_name = params.get("driver_name")

    if driver_name:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )

    if del_dump_cmd:
        session.sendline(del_dump_cmd)

    if params.get("config_cmds"):
        error_context.context("Configure guest for dump", test.log.info)
        # Wait guest fully boot up, or configure command may fail in windows
        time.sleep(30)
        reg_cmds = params.get("config_cmds").split(",")
        msg = "Configure the guest"
        for reg_cmd in reg_cmds:
            cmd = params.get(reg_cmd.strip())
            msg += " The command is %s " % cmd
            error_context.context(msg)
            s, o = session.cmd_status_output(cmd, 360)
            if s:
                test.fail("Fail command: %s. Output: %s" % (cmd, o))

    if params.get("reboot_after_config") == "yes":
        error_context.context("Reboot guest", test.log.info)
        session = vm.reboot(timeout=timeout * 2)

    try:
        if nmi_cmd:
            error_context.context(
                "Send inject-nmi or nmi from host to guest", test.log.info
            )
            vm.monitor.send_args_cmd(nmi_cmd)
        # Wait guest create dump file.
        if manual_reboot_cmd:
            bsod_time = params.get("bsod_time", 160)
            test.log.info("Waiting guest for creating dump file" " (%ssec)", bsod_time)
            time.sleep(bsod_time)
            error_context.context("Send a system_reset monitor command", test.log.info)
            vm.monitor.send_args_cmd(manual_reboot_cmd)

        session = vm.wait_for_login(timeout=timeout)

        if check_dump_cmd:
            error_context.context(
                "Verify whether the dump files are " "generated", test.log.info
            )
            s, o = session.cmd_status_output(check_dump_cmd, 360)
            test.log.debug("Output for check_dump_cmd command: %s", o)
            if s:
                err_msg = "Could not find dump files in guest. Output: '%s'" % o
                test.fail(err_msg)

        error_context.context("Analyze dump file with windbg", test.log.info)
        if session.cmd_status(params["chk_sdk_ins"]):
            win_dump_utils.install_windbg(
                test, params, session, timeout=params.get("wdbg_timeout", 600)
            )
        error_context.context("Disable security alert", test.log.info)
        win_dump_utils.disable_security_alert(params, session)
        session.cmd(params["save_path_cmd"])
        win_dump_utils.dump_windbg_check(test, params, session)
    finally:
        if session is not None and del_dump_cmd:
            try:
                session.sendline(del_dump_cmd)
            except Exception as e:
                # Ignore cleanup exception to avoid it overriding
                # the actual fault.
                test.log.warning("Failed to delete dump files: '%s'", e)
