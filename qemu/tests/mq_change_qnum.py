import re

import aexpect
from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    MULTI_QUEUE chang queues number test

    1) Boot up VM, and login guest
    2) Check guest pci msi support and reset it as expection
    3) Enable the queues in guest
    4) Run bg_stress_test(pktgen, netperf or file copy) if needed
    5) Change queues number repeatly during stress test running
    6) Ping external host (local host, if external host not available)

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def change_queues_number(session, ifname, q_number, queues_status=None):
        """
        Change queues number
        """
        if not queues_status:
            queues_status = get_queues_status(session, ifname)

        mq_set_cmd = "ethtool -L %s combined %d" % (ifname, q_number)
        status, output = session.cmd_status_output(mq_set_cmd)
        cur_queues_status = get_queues_status(session, ifname)

        err_msg = ""
        expect_q_number = q_number
        if (
            q_number != queues_status[1]
            and q_number <= queues_status[0]
            and q_number > 0
        ):
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

        return [int(_) for _ in cur_queues_status]

    def get_queues_status(session, ifname, timeout=240):
        """
        Get queues status
        """
        mq_get_cmd = "ethtool -l %s" % ifname
        nic_mq_info = session.cmd_output(mq_get_cmd, timeout=timeout)
        queues_reg = re.compile(r"Combined:\s+(\d)", re.I)
        queues_info = queues_reg.findall(" ".join(nic_mq_info.splitlines()))
        if len(queues_info) != 2:
            err_msg = "Oops, get guest queues info failed, "
            err_msg += "make sure your guest support MQ.\n"
            err_msg += "Check cmd is: '%s', " % mq_get_cmd
            err_msg += "Command output is: '%s'." % nic_mq_info
            test.cancel(err_msg)
        return [int(x) for x in queues_info]

    def enable_multi_queues(vm):
        sess = vm.wait_for_login(timeout=login_timeout)
        error_context.context("Enable multi queues in guest.", test.log.info)
        for nic_index, nic in enumerate(vm.virtnet):
            ifname = utils_net.get_linux_ifname(sess, nic.mac)
            queues = int(nic.queues)
            change_queues_number(sess, ifname, queues)

    def ping_test(dest_ip, ping_time, lost_raito, session=None):
        status, output = utils_test.ping(
            dest=dest_ip, timeout=ping_time, session=session
        )
        packets_lost = utils_test.get_loss_ratio(output)
        if packets_lost > lost_raito:
            err = " %s%% packages lost during ping. " % packets_lost
            err += "Ping command log:\n %s" % "\n".join(output.splitlines()[-3:])
            test.fail(err)

    error_context.context("Init guest and try to login", test.log.info)
    login_timeout = int(params.get("login_timeout", 360))
    bg_stress_test = params.get("run_bgstress")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    if params.get("pci_nomsi", "no") == "yes":
        error_context.context("Disable pci msi in guest", test.log.info)
        utils_test.update_boot_option(vm, args_added="pci=nomsi")
        vm.wait_for_login(timeout=login_timeout)

    enable_multi_queues(vm)

    session = vm.wait_for_login(timeout=login_timeout)
    s_session = None
    bg_ping = params.get("bg_ping")
    b_ping_lost_ratio = int(params.get("background_ping_package_lost_ratio", 5))
    f_ping_lost_ratio = int(params.get("final_ping_package_lost_ratio", 5))
    guest_ip = vm.get_address()
    b_ping_time = int(params.get("background_ping_time", 60))
    f_ping_time = int(params.get("final_ping_time", 60))
    bg_test = None
    try:
        ifnames = []
        for nic_index, nic in enumerate(vm.virtnet):
            ifname = utils_net.get_linux_ifname(session, vm.virtnet[nic_index].mac)
            ifnames.append(ifname)

        error_context.context("Run test %s background" % bg_stress_test, test.log.info)
        stress_thread = utils_misc.InterruptedThread(
            utils_test.run_virt_sub_test,
            (test, params, env),
            {"sub_type": bg_stress_test},
        )
        stress_thread.start()

        if bg_ping == "yes":
            error_context.context("Ping guest from host", test.log.info)
            args = (guest_ip, b_ping_time, b_ping_lost_ratio)
            bg_test = utils_misc.InterruptedThread(ping_test, args)
            bg_test.start()

        error_context.context("Change queues number repeatly", test.log.info)
        repeat_counts = int(params.get("repeat_counts", 10))
        for nic_index, nic in enumerate(vm.virtnet):
            if "virtio" not in nic["nic_model"]:
                continue
            queues = int(vm.virtnet[nic_index].queues)
            if queues == 1:
                test.log.info("Nic with single queue, skip and continue")
                continue
            ifname = ifnames[nic_index]
            default_change_list = range(1, int(queues + 1))
            change_list = params.get("change_list")
            if change_list:
                change_list = change_list.split(",")
            else:
                change_list = default_change_list

            for repeat_num in range(1, repeat_counts + 1):
                error_context.context(
                    "Change queues number -- %sth" % repeat_num, test.log.info
                )
                try:
                    queues_status = get_queues_status(session, ifname)
                    for q_number in change_list:
                        queues_status = change_queues_number(
                            session, ifname, int(q_number), queues_status
                        )
                except aexpect.ShellProcessTerminatedError:
                    vm = env.get_vm(params["main_vm"])
                    session = vm.wait_for_login(timeout=login_timeout)
                    queues_status = get_queues_status(session, ifname)
                    for q_number in change_list:
                        queues_status = change_queues_number(
                            session, ifname, int(q_number), queues_status
                        )

        if params.get("ping_after_changing_queues", "yes") == "yes":
            default_host = "www.redhat.com"
            ext_host = utils_net.get_default_gateway(session)
            if not ext_host:
                # Fallback to a hardcode host, eg:
                test.log.warning(
                    "Can't get specified host," " Fallback to default host '%s'",
                    default_host,
                )
                ext_host = default_host
            s_session = vm.wait_for_login(timeout=login_timeout)
            txt = "ping %s after changing queues in guest."
            error_context.context(txt, test.log.info)
            ping_test(ext_host, f_ping_time, f_ping_lost_ratio, s_session)

        if stress_thread:
            error_context.context("wait for background test finish", test.log.info)
            try:
                stress_thread.join()
            except Exception as err:
                err_msg = "Run %s test background error!\n "
                err_msg += "Error Info: '%s'"
                test.error(err_msg % (bg_stress_test, err))

    finally:
        if session:
            session.close()
        if s_session:
            s_session.close()
        if bg_test:
            error_context.context(
                "Wait for background ping test finish.", test.log.info
            )
            try:
                bg_test.join()
            except Exception as err:
                txt = "Fail to wait background ping test finish. "
                txt += "Got error message %s" % err
                test.fail(txt)
