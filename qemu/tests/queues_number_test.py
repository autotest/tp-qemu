import re

from virttest import error_context, utils_misc, utils_net, utils_test

from provider import netperf_test


@error_context.context_aware
def run(test, params, env):
    """
    MULTI_QUEUE chang queues number test
    1) Boot up VM, and login guest
    2) Enable the queues in guest
    3) Run netperf_and_ping test
    4) Change queues number repeatedly during netperf_and_ping stress testing
    5) Reboot VM
    6) Repeat above 1-4 steps
    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def change_queues_number(ifname, q_number, queues_status=None):
        """
        change queues number
        """
        if not queues_status:
            queues_status = get_queues_status(ifname)
        mq_set_cmd = "ethtool -L %s combined %d" % (ifname, q_number)
        output = session.cmd_output(mq_set_cmd)
        cur_queues_status = get_queues_status(ifname)

        err_msg = ""
        expect_q_number = q_number
        if q_number != queues_status[1] and q_number <= queues_status[0]:
            if (
                cur_queues_status[1] != q_number
                or cur_queues_status[0] != queues_status[0]
            ):
                err_msg = "Param is valid, but change queues failed, "
        elif cur_queues_status != queues_status:
            if q_number != queues_status[1]:
                err_msg = "Param is invalid, "
            err_msg += "Current queues value is not expected, "
            expect_q_number = queues_status[1]

        if len(err_msg) > 0:
            err_msg += "current queues set is %s, " % cur_queues_status[1]
            err_msg += "max allow queues set is %s, " % cur_queues_status[0]
            err_msg += "when run cmd: '%s', " % mq_set_cmd
            err_msg += "expect queues are %s," % expect_q_number
            err_msg += "expect max allow queues are %s, " % queues_status[0]
            err_msg += "output: '%s'" % output
            test.fail(err_msg)

        return cur_queues_status

    def get_queues_status(ifname):
        """
        Get queues status
        """
        mq_get_cmd = "ethtool -l %s" % ifname
        nic_mq_info = session.cmd_output(mq_get_cmd)
        queues_reg = re.compile(r"Combined:\s+(\d)", re.I)
        queues_info = queues_reg.findall(" ".join(nic_mq_info.splitlines()))
        if len(queues_info) != 2:
            err_msg = "Oops, get guest queues info failed, "
            err_msg += "make sure your guest support MQ.\n"
            err_msg += "Check cmd is: '%s', " % mq_get_cmd
            err_msg += "Command output is: '%s'." % nic_mq_info
            test.cancel(err_msg)
        return [int(x) for x in queues_info]

    def ping_test(dest_ip, ping_time, ping_lost_ratio):
        """
        ping guest from host,until change queues finished.
        """
        _, output = utils_net.ping(dest=dest_ip, timeout=ping_time)
        packets_lost = utils_test.get_loss_ratio(output)
        if packets_lost > ping_lost_ratio:
            err = " %s%% packages lost during ping. " % packets_lost
            err += "Ping command log:\n %s" % "\n".join(output.splitlines()[-3:])
            test.fail(err)

    login_timeout = params.get_numeric("login_timeout", 360)
    netperf_stress = params.get("run_bgstress")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_serial_login(timeout=login_timeout)
    guest_ip = vm.get_address()
    ping_lost_ratio = params.get_numeric("background_ping_package_lost_ratio", 5)
    ping_time = params.get_numeric("background_ping_time")
    required_reboot = True
    bg_test = True
    try:
        while bg_test:
            session = vm.wait_for_login()
            session_serial = vm.wait_for_serial_login(timeout=login_timeout)
            error_context.context("Enable multi queues in guest.", test.log.info)
            for nic in vm.virtnet:
                ifname = utils_net.get_linux_ifname(session_serial, nic.mac)
                queues = int(nic.queues)
                change_queues_number(ifname, queues)
            error_context.context(
                "Run test %s background" % netperf_stress, test.log.info
            )
            stress_thread = utils_misc.InterruptedThread(
                netperf_test.netperf_stress, (test, params, vm)
            )
            stress_thread.start()

            # ping test
            error_context.context("Ping guest from host", test.log.info)
            args = (guest_ip, ping_time, ping_lost_ratio)
            bg_ping = utils_misc.InterruptedThread(ping_test, args)
            bg_ping.start()

            error_context.context("Change queues number repeatedly", test.log.info)
            repeat_counts = params.get_numeric("repeat_counts")
            for nic in vm.virtnet:
                queues = int(nic.queues)
                if queues == 1:
                    test.log.info("Nic with single queue, skip and continue")
                    continue
                ifname = utils_net.get_linux_ifname(session_serial, nic.mac)
                change_list = params.get("change_list").split(",")
                for repeat_num in range(repeat_counts):
                    error_context.context(
                        "Change queues number -- %sth" % repeat_num, test.log.info
                    )
                    queues_status = get_queues_status(ifname)
                    for q_number in change_list:
                        queues_status = change_queues_number(
                            ifname, int(q_number), queues_status
                        )

            test.log.info("wait for background test finish")
            try:
                stress_thread.join()
            except Exception as err:
                err_msg = "Run %s test background error!\n "
                err_msg += "Error Info: '%s'"
                test.error(err_msg % (netperf_stress, err))

            test.log.info("Wait for background ping test finish.")
            try:
                bg_ping.join()
            except Exception as err:
                txt = "Fail to wait background ping test finish. "
                txt += "Got error message %s" % err
                test.fail(txt)

            if required_reboot:
                test.log.info("Rebooting guest ...")
                vm.reboot()
                required_reboot = False
            else:
                bg_test = False
    finally:
        if session:
            session.close()
        if session_serial:
            session_serial.close()
