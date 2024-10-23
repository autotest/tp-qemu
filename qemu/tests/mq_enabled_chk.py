import re

from virttest import env_process, error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    MULTI_QUEUE enabled by default check test

    1) Boot up a VM, and login to the guest
    2) Check the queues according to the value set in qemu cmd line for
       smp and queues
    3) do ping test

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_queues_status(session, ifname, timeout=240):
        """
        Get queues status

        :param session: guest session
        :param ifname: interface name
        :param timeout: timeout of session.cmd_output

        :return: queues status list
        """
        mq_get_cmd = "ethtool -l %s" % ifname
        nic_mq_info = session.cmd_output(mq_get_cmd, timeout=timeout, safe=True)
        queues_reg = re.compile(r"Combined:\s+(\d)", re.I)
        queues_info = queues_reg.findall(" ".join(nic_mq_info.splitlines()))
        if len(queues_info) != 2:
            err_msg = "Oops, get guest queues info failed, "
            err_msg += "make sure your guest support MQ.\n"
            err_msg += "Check cmd is: '%s', " % mq_get_cmd
            err_msg += "Command output is: '%s'." % nic_mq_info
            test.cancel(err_msg)
        return [int(x) for x in queues_info]

    def chk_mq_enabled(vm, queues):
        """
        Check whether MQ value set in qemu cmd line fits the value in guest

        :param vm: guest vm
        :param queues: queues value in qemu cmd line
        """
        login_timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=login_timeout)

        mac = vm.get_mac_address(0)
        ifname = utils_net.get_linux_ifname(session, mac)
        queues_status_list = get_queues_status(session, ifname)

        session.close()
        if not queues_status_list[0] == queues or not queues_status_list[1] == min(
            queues, int(vm.cpuinfo.smp)
        ):
            txt = "Pre-set maximums Combined should equals to queues in qemu"
            txt += " cmd line.\n"
            txt += "Current hardware settings Combined should be the min of "
            txt += "queues and smp.\n"
            txt += "Pre-set maximum Combined is: %s, " % queues_status_list[0]
            txt += " queues in qemu cmd line is: %s.\n" % queues
            txt += "Current hardware settings Combined "
            txt += "is: %s, " % queues_status_list[1]
            txt += " smp in qemu cmd line is: %s." % int(vm.cpuinfo.smp)
            test.fail(txt)

    error_context.context("Init the guest and try to login", test.log.info)
    queues_list = params["queues_list"].split()

    for queues in queues_list:
        params["queues"] = int(queues)
        params["start_vm"] = "yes"

        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        chk_mq_enabled(vm, int(queues))
        guest_ip = vm.get_address()
        status, output = utils_net.ping(guest_ip, 10, session=None, timeout=20)
        if utils_test.get_loss_ratio(output) > 0:
            test.fail("Packet lost while doing ping test")

        vm.destroy(gracefully=True)
