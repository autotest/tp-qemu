import re

from virttest import env_process, error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Check link speed and duplex settings in guest to match the
    configuration named by params in qemu command lines.

    1) Start vm with default settings
    2) Check speed and duplex in guest, to match the default settings
    3) Reboot vm with command line params: "speed=1000,duplex=full"
    4) Check speed and duplex in guest again, to match the argument above
    5) Perform ping test between host and guest, to check nic avaliability

    param test: the test object
    param params: the test params
    param env: test environment
    """

    def get_speed_duplex_traceview():
        """
        Get the speed and duplex information by traceview.exe.

        return: a tuple of (speed, duplex), whitch speed is measured by bps,
                and duplex is a 'full' or 'half'.
        """
        error_context.context(
            "Check speed and duplex info from the traceview", test.log.info
        )
        log = utils_net.dump_traceview_log_windows(params, vm)
        check_pattern = "Speed=(\\d+).+Duplex=(\\w+)$"
        result = re.search(check_pattern, log, re.MULTILINE)
        if result:
            return (int(result.group(1)), result.group(2).lower())
        test.fail("Can't get speed or duplex info from traceview")

    def get_speed_duplex_powershell(session):
        """
        Get the speed and duplex information from powershell commands.

        return: a tuple of (speed, duplex), whitch speed is measured by bps,
                and duplex is a 'full' or 'half'.
        """
        error_context.context(
            "Check speed and duplex info from powershell", test.log.info
        )
        check_speed_cmd = params["check_speed_powershell_cmd"]
        status, output = session.cmd_status_output(check_speed_cmd)
        if status:
            test.fail(
                "Failed to get speed info from powershell, "
                "status=%s, output=%s" % (status, output)
            )
        lines = output.strip().split("\n")
        if len(lines) > 2:
            result = lines[2].strip().split()
            if len(result) > 1:
                return (
                    int(result[0]),
                    "full" if result[1].lower() == "true" else "half",
                )
        test.fail("Can't get speed or duplex info from powershell")

    def run_test_windows(session, tar_speed, tar_duplex):
        """
        Start the test on windows guests. Check whether the speed and duplex
        information of the guest's nic matches the input params.

        param tar_speed: target speed expected
        param tar_duplex: target duplex expected
        """
        # convert to bps unit
        tar_speed = tar_speed * 1000000
        error_context.context(
            "Check if the driver is installed and verified", test.log.info
        )
        driver_name = params.get("driver_name", "netkvm")
        run_powershell = params.get("run_powershell", "yes") == "yes"
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )
        if run_powershell:
            check_speed_duplex_windows(
                session, tar_speed, tar_duplex, method="powershell"
            )
        # run traceview after powershell, for it will invalid session
        check_speed_duplex_windows(session, tar_speed, tar_duplex)

    def check_speed_duplex_windows(session, tar_speed, tar_duplex, method="traceview"):
        """
        Check the speed and duplex with certain method.

        param tar_speed: target speed expected
        param tar_duplex: target duplex expected
        param method: the method to check, one of 'traceview' and 'powershell'
        """
        if method == "traceview":
            speed, duplex = get_speed_duplex_traceview()
        elif method == "powershell":
            speed, duplex = get_speed_duplex_powershell(session)
        else:
            test.error("Method %s not supported", method)
        if speed != tar_speed or duplex != tar_duplex:  # pylint: disable=E0606
            test.fail(
                "The speed and duplex is incorrect in %s, "
                "with speed=%s, duplex=%s" % (method, speed, duplex)
            )

    def get_speed_duplex_linux(session):
        """
        Get the speed and duplex information on linux guests.

        return: a tuple of (speed, duplex), which speed is measured by mbps,
                and duplex is one of 'half' and 'full'.
        """
        error_context.context("Get speed & duplex info", test.log.info)
        mac = vm.get_mac_address(0)
        ethname = utils_net.get_linux_ifname(session, mac)
        check_speed_cmd = params["check_speed_cmd"] % ethname
        status, output = session.cmd_status_output(check_speed_cmd)
        if status:
            test.fail(
                "Failed to get speed info," "status=%s, ouput=%s" % (status, output)
            )
        test.log.info(output)
        result = re.findall(r"(?:Speed:\s+(\d+)Mb/s)|(?:Duplex:\s+(\w+))", output)
        if len(result) < 2:
            test.error("Can't get speed or duplex info")
        speed = int(result[0][0])
        duplex = result[1][1].lower()
        return (speed, duplex)

    def run_test_linux(session, tar_speed, tar_duplex):
        """
        Start the test on linux guests. Check whether the speed and duplex
        information of the guest's nic matches the input params.

        param tar_speed: target speed expected
        param tar_duplex: target duplex expected
        """
        speed, duplex = get_speed_duplex_linux(session)
        if speed != tar_speed or duplex != tar_duplex:
            test.fail(
                "The speed and duplex is incorrect, "
                "with speed=%s, duplex=%s" % (speed, duplex)
            )

    def run_test(session, tar_speed, tar_duplex):
        """
        Start the test according to the guest's os.

        param tar_speed: target speed expected
        param tar_duplex: target duplex expected
        """
        if os_type == "windows":
            run_test_windows(session, tar_speed, tar_duplex)
        elif os_type == "linux":
            run_test_linux(session, tar_speed, tar_duplex)

    timeout = params.get("timeout", 360)
    os_type = params.get("os_type")
    default_tar_speed = int(params.get("default_tar_speed"))
    modify_tar_speed = int(params.get("modify_tar_speed"))
    tar_duplex = params.get("tar_duplex")
    modify_speed_param = params.get("modify_speed_param")

    # check default value only under windows guest
    if os_type == "windows":
        vm = env.get_vm(params["main_vm"])
        session = vm.wait_for_login(timeout=timeout)
        try:
            run_test(session, default_tar_speed, tar_duplex)
        finally:
            session.close()
        vm.destroy(gracefully=True)

    params["nic_extra_params"] = modify_speed_param
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    try:
        run_test(session, modify_tar_speed, tar_duplex)
    finally:
        session.close()
    guest_ip = vm.get_address()
    status, output = utils_test.ping(guest_ip, 10, timeout=15)
    if status:
        test.fail("Fail to perfrom ping test, status=%s, output=%s" % (status, output))
    lost_ratio = utils_test.get_loss_ratio(output)
    if lost_ratio > 0:
        test.fail("Ping loss ratio is %s" % lost_ratio)
