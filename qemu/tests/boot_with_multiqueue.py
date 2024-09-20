import re

from virttest import error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest with different vectors, then do file transfer tests.

    1) Boot up VM with certain vectors.
    2) Check guest msi & queues info
    3) Start 10 scp file transfer tests

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    login_timeout = int(params.get("login_timeout", 360))
    cmd_timeout = int(params.get("cmd_timeout", 240))

    # boot the vm with the queues
    queues = int(params["queues"])
    error_context.context("Boot the guest with queues = %s" % queues, test.log.info)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    # enable multi-queues for linux guest
    if params["os_type"] == "linux":
        nic = vm.virtnet[0]
        ifname = utils_net.get_linux_ifname(session, nic.mac)
        set_queue_cmd = "ethtool -L %s combined %s" % (ifname, queues)
        status, output = session.cmd_status_output(
            set_queue_cmd, timeout=cmd_timeout, safe=True
        )
        if status:
            err = "Failed to set queues to %s with status = %s and output= %s"
            err %= (queues, status, output)
            test.fail(err)
        check_queue_cmd = "ethtool -l %s" % ifname
        output = session.cmd_output(check_queue_cmd, timeout=cmd_timeout)
        if len(re.findall(r"Combined:\s+%d\s" % queues, output)) != 2:
            test.fail("Fail to set queues to %s on %s" % (queues, nic.nic_name))

        # check the msi for linux guest
        error_context.context("Check the msi number in guest", test.log.info)
        devices = session.cmd_output(
            "lspci | grep Ethernet", timeout=cmd_timeout, safe=True
        ).strip()
        for device in devices.split("\n"):
            if not device:
                continue
            d_id = device.split()[0]
            msi_check_cmd = params["msi_check_cmd"] % d_id
            status, output = session.cmd_status_output(
                msi_check_cmd, timeout=cmd_timeout, safe=True
            )
            find_result = re.search(r"MSI-X: Enable\+\s+Count=(\d+)", output)
            if not find_result:
                test.fail("No MSI info in output: %s" % output)
            msis = int(find_result.group(1))
            if msis != 2 * queues + 2:
                test.fail("MSI not correct with output: %s" % output)
    else:
        # verify driver
        error_context.context(
            "Check if the driver is installed and " "verified", test.log.info
        )
        driver_name = params.get("driver_name", "netkvm")
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, cmd_timeout
        )
        # check the msi for windows guest with trace view
        error_context.context("Check the msi number in guest", test.log.info)
        msis, cur_queues = utils_net.get_msis_and_queues_windows(params, vm)
        if cur_queues != queues or msis != 2 * queues + 2:
            test.fail("queues not correct with %s, expect %s" % (cur_queues, queues))

    # start scp test
    error_context.context("Start scp file transfer test", test.log.info)
    scp_count = int(params.get("scp_count", 10))
    for i in range(scp_count):
        utils_test.run_file_transfer(test, params, env)
    if session:
        session.close()
