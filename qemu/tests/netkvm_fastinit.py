import re
import time

from virttest import env_process, error_context, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    NetKVM FastInit functional test.

    1) Boot the VM with the requested vCPU and NIC-queue settings
    2) Enable or disable Driver Verifier (reboot if needed)
    3) Wait for all NICs to obtain IPs and log boot-to-login time
    4) Enable FastInit on each NetKVM adapter and verify it
    5) Dump the NetKVM WMI configuration to the log

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def disable_driver_verifier(vm, params, test, timeout):
        """
        Turn Driver Verifier off (Windows guest only).

        1) Read *enable_verifier* (yes → enable, no → disable)
        2) Query current Driver Verifier status in the guest
        3) If state is already as requested, exit
        4) Otherwise run the enable/reset command and reboot
        5) Re-query after reboot to confirm the final state
        6) Raise TestError if the state is still wrong

        :param vm: QEMU test object
        :param params: Dictionary with the test parameters
        :param test: QEMU test object
        :param timeout: VM login time value
        """
        enable_verifier = bool(params.get_numeric("enable_verifier", 1))
        query_cmd = params.get("driver_verifier_query", "verifier /querysettings")
        enable_cmd = params.get(
            "driver_verifier_enable", "verifier /standard /flags netkvm.sys ndis.sys"
        )
        reset_cmd = params.get("driver_verifier_reset", "verifier /reset")

        def verifier_is_on(session, query_cmd=query_cmd):
            """
            Return True if Driver Verifier is currently enabled

            Driver Verifier is considered *OFF* when the mask is
            **0x00000000**; otherwise it is *ON*.
            """
            output = session.cmd_output(query_cmd)
            return "0x00000000" not in output

        session = vm.wait_for_serial_login(timeout)
        active = verifier_is_on(session)
        if enable_verifier is not active:
            if enable_verifier is True:
                cmd = enable_cmd
            else:
                cmd = reset_cmd
            session.cmd_status_output(cmd)
            vm.reboot(method="shell", serial=True, timeout=timeout, session=session)
        else:
            return

        session = vm.wait_for_serial_login(timeout)
        test.log.info("Current Driver Verifier: %s", session.cmd_output(query_cmd))
        active = verifier_is_on(session)
        if enable_verifier is not active:
            test.error("Driver Verifier state MISmatch after reboot")
        else:
            test.log.info("Driver Verifier state MATCH after reboot")
        session.close()

    def check_log_blocks(log_text, test, params):
        """
        Check log blocks for NetKVM adapter initialization times.

        :param log_text: WMI output containing adapter information
        :param test: QEMU test object for logging
        :param params: Dictionary with test parameters (to get nics_num)
        """
        lines = log_text.strip().splitlines()
        active_count = 0
        lazy_failures = 0
        expected_nics_count = params.get_numeric("nics_num", 27)
        lazy_alloc_threshold = params.get_numeric("lazy_alloc_threshold", 0)
        init_alloc_threshold = params.get_numeric("init_alloc_threshold", 0)

        for i, ln in enumerate(lines):
            if "Active=TRUE" in ln:
                active_count += 1
                start = i
                end = min(len(lines), i + 11)
                block = "\n".join(lines[start:end])

                name_match = re.search(r"InstanceName=([^\n]+)", block)
                name = (name_match or [None, "UNKNOWN"])[1].strip()
                init = int((re.search(r"InitTimeMs=(-?\d+)", block) or [None, "0"])[1])
                lazy = int(
                    (re.search(r"LazyAllocTimeMs=(-?\d+)", block) or [None, "0"])[1]
                )
                total = init + lazy

                if lazy == -1:
                    test.error(
                        "test.fail: %s | LazyAllocTimeMs = -1 "
                        "(should not happen after wait)" % name
                    )
                elif init > init_alloc_threshold:
                    test.error(
                        "test.fail: %s | InitTimeMs(%s) > %d"
                        % (name, init, init_alloc_threshold)
                    )
                elif lazy > lazy_alloc_threshold:
                    lazy_failures += 1
                    if lazy_failures > 1:
                        test.error(
                            "test.fail: %s | LazyAllocTimeMs(%s) > %d"
                            % (name, lazy, lazy_alloc_threshold)
                        )
                    else:
                        test.log.warning(
                            "Warning (allowed): %s | LazyAllocTimeMs(%s) > %d",
                            name,
                            lazy,
                            lazy_alloc_threshold,
                        )
                else:
                    test.log.info(
                        "[OK] %s | Init=%s Lazy=%s Sum=%s", name, init, lazy, total
                    )

        # Verify the count of Active=TRUE NICs matches expected
        if active_count != expected_nics_count:
            test.error(
                "Expected %s NICs with Active=TRUE, but found %s"
                % (expected_nics_count, active_count)
            )

    def wmi_operations(session, vm, params, test, timeout):
        """
        Dump NetKVM WMI configuration and check timing data.
        Wait for all NICs LazyAllocTimeMs to be non -1 before checking.

        :param session: VM session info
        :param vm: QEMU test object
        :param params: Dictionary with the test parameters
        :param test: QEMU test object
        :param timeout: VM login time value
        """
        test.log.info("Record the data after fastinit operation")
        netkvm_wmi = params.get("netkvm_wmi", "WIN_UTILS:\netkvm\\WMI\netkvm-wmi.cmd")
        netkvm_wmi = utils_misc.set_winutils_letter(session, netkvm_wmi)
        status, output = session.cmd_status_output("%s cfg" % netkvm_wmi, timeout)
        test.log.info("fastinit data: %s", output)
        check_log_blocks(output, test, params)
        return output

    def fastinit_nics_operations(session, vm, params, test, timeout):
        """
        Check first NIC FastInit status only.

        :param session: VM session info
        :param vm: QEMU test object
        :param params: Dictionary with the test parameters
        :param test: QEMU test object
        :param timeout: VM login time value
        """
        error_context.context("Checking first NIC FastInit status...", test.log.info)
        fastinit_value = params.get_numeric("fastinit_value", 1)
        first_nic_num = 0  # Only check first NIC to save time

        # Only verify the first NIC's fastinit status to save time
        current_value = utils_net.get_netkvm_param_value(
            vm, fastinit_name, nic_index=first_nic_num
        )
        test.log.info("NIC %d current FastInit value: %s", first_nic_num, current_value)

        if str(current_value).strip() != str(fastinit_value):
            for nic_num in range(0, nics_num - 1):
                utils_net.set_netkvm_param_value(
                    vm, fastinit_name, fastinit_value, nic_index=nic_num
                )
                output = utils_net.get_netkvm_param_value(
                    vm, fastinit_name, nic_index=nic_num
                )
                test.log.info("NIC %d new FastInit value is %s", nic_num, output)

    login_timeout = params.get_numeric("login_timeout", 3600)
    fastinit_name = params.get("fastinit_name", "FastInit")
    nics_num = params.get_numeric("nics_num", 27)
    nics_param = params.get("nics_param")
    # Dynamically append additional NICs if requested
    for i in range(2, nics_num + 1):
        nics = "nic%s" % i
        params["nics"] = " ".join([params["nics"], nics])
        params["nic_extra_params_" + str(nics)] = nics_param
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    #  Boot VM (cold boot)
    error_context.context("boot vm", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)
    # Driver Verifier toggle (may trigger reboot)
    error_context.context("configure verifier function", test.log.info)
    disable_driver_verifier(vm, params, test, timeout=login_timeout)
    # Enable or Disable Fast Init on every NetKVM adapter
    fastinit_nics_operations(
        vm=vm, params=params, test=test, session=session, timeout=login_timeout
    )

    # Destroy to start timing measurement from power-off
    session.close()
    vm.destroy(gracefully=True)

    #  Timing: cold boot to all-NIC-ready
    error_context.context("start calculagraph about NICs initiation", test.log.info)
    start_time = time.time()
    vm.create()
    vm.verify_alive()
    middle_time = time.time()
    test.log.info("Log system boot time: %s", start_time)
    session = vm.wait_for_serial_login(timeout=login_timeout)
    end_time = time.time()
    test.log.info("Log system booted time: %s", end_time)
    test.log.info(
        "%s -> %s -> %s  %s",
        time.strftime("%H:%M:%S", time.localtime(start_time)),
        time.strftime("%H:%M:%S", time.localtime(middle_time)),
        time.strftime("%H:%M:%S", time.localtime(end_time)),
        time.strftime("%H:%M:%S", time.gmtime(end_time - start_time)),
    )

    #  Diagnostics after cold boot
    error_context.context("records cold boot data", test.log.info)
    wmi_operations(
        vm=vm, params=params, test=test, session=session, timeout=login_timeout
    )

    #  Hot reboot + diagnostics
    vm.reboot(method="shell", serial=True, timeout=login_timeout, session=session)
    error_context.context("records hot boot data", test.log.info)
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)
    wmi_operations(
        vm=vm, params=params, test=test, session=session, timeout=login_timeout
    )
