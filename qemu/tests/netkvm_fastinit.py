import time

from virttest import env_process, utils_misc, utils_net


def run(test, params, env):
    """
    NetKVM FastInit functional test

    1) Boot the VM with the requested vCPU and NIC-queue settings
    2) Enable or disable Driver Verifier (reboot if needed)
    3) Wait for all NICs to obtain IPs and log boot-to-login time
    4) Enable FastInit on each NetKVM adapter and verify it
    5) Dump the NetKVM WMI configuration to the log

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def disable_driver_verifier(vm, params, test):
        """
        Turn Driver Verifier off (Windows guest only)

        1) Read *enable_verifier* (yes → enable, no → disable)
        2) Query current Driver Verifier status in the guest
        3) If state is already as requested, exit
        4) Otherwise run the enable/reset command and reboot
        5) Re-query after reboot to confirm the final state
        6) Raise TestError if the state is still wrong

        :param vm: QEMU test object
        :param params: Dictionary with the test parameters
        :param test: QEMU test object
        """
        login_timeout = params.get_numeric("login_timeout", 3600)
        enable_verifier = bool(params.get("enable_verifier", True))
        query_cmd = params.get("driver_verifier_query", "verifier /querysettings")
        enable_cmd = params.get("driver_verifier_enable", "verifier /standard /all")
        reset_cmd = params.get("driver_verifier_reset", "verifier /reset")

        def verifier_is_on(session, query_cmd=query_cmd):
            return ".sys" in session.cmd_output(query_cmd)

        session = vm.wait_for_serial_login(timeout=login_timeout)
        active = verifier_is_on(session)
        test.log.info("Driver Verifier enabled: %s", active)
        if enable_verifier is not active:
            if enable_verifier is True:
                cmd = enable_cmd
            else:
                cmd = reset_cmd
            session.cmd_output(cmd)
            vm.reboot(
                method="system_reset",
                serial=True,
                timeout=login_timeout,
                session=session,
            )
        else:
            return

        session = vm.wait_for_serial_login(timeout=login_timeout)
        active = verifier_is_on(session)
        test.log.info("Driver Verifier enabled: %s", active)
        enable_verifier = params.get("enable_verifier", True)
        if active is not enable_verifier:
            test.error("Driver Verifier state MISmatch after reboot")
        else:
            test.log.info("Driver Verifier state MATCH after reboot")
        session.close()

    nics_num = int(params.get("nics_num", 8))
    nics_param = params.get("nics_param")
    for i in range(2, nics_num + 1):
        nics = "nic%s" % i
        params["nics"] = " ".join([params["nics"], nics])
        params["nic_extra_params_" + str(nics)] = nics_param

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    start_time = time.time()
    test.log.info("Log system boot time: %s", start_time)

    disable_driver_verifier(vm, params, test)

    login_timeout = params.get_numeric("login_timeout")
    session = vm.wait_for_serial_login(timeout=600)
    nics_num_checking_cmd = params.get("nics_num_checking_cmd")
    nics_num = params.get_numeric("nics_num", 27)
    utils_misc.wait_for(
        lambda: int(session.cmd_output(nics_num_checking_cmd, timeout=60)) == nics_num,
        timeout=1620,
        first=0,
        step=60,
        text="waiting for all nics to get ip",
    )
    end_time = time.time()
    test.log.info("Log system booted time: %s", end_time)
    test.log.info(
        "%s -> %s  %s",
        time.strftime("%H:%M:%S", time.localtime(start_time)),
        time.strftime("%H:%M:%S", time.localtime(end_time)),
        time.strftime("%H:%M:%S", time.gmtime(end_time - start_time)),
    )

    fastinit_name = params.get("fastinit_name", "FastInit")
    fastinit_value = params.get_numeric("fastinit_value", 1)
    for nic_num in range(0, nics_num - 1):
        utils_net.set_netkvm_param_value(
            vm, fastinit_name, fastinit_value, nic_index=nic_num
        )
        output = utils_net.get_netkvm_param_value(vm, fastinit_name, nic_index=nic_num)
        test.log.info("NIC %d FastInit value is %s", nic_num, output)

    test.log.info("Record the data after fastinit operation")
    netkvm_wmi = params.get("netkvm_wmi")
    netkvm_wmi = utils_misc.set_winutils_letter(session, netkvm_wmi)
    status, output = session.cmd_status_output(
        "%s cfg" % netkvm_wmi, timeout=login_timeout
    )
    test.log.info("fastinit data: %s", output)
