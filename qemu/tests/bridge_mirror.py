import re
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test port mirror with linux bridge backend.

    1) Create a private bridge
    2) Set private bridge promisc mode and up
    3) Boot 3 VMs over private bridge
    4) Mirror all traffic on bridge to tap device connected to VM1
    5) Start tcpdump in VM1 to dump icmp packets from VM2 to VM3
    6) Ping VM3 from VM2
    7) Stop Ping in VM2
    8) Stop tcpdump and check results

    :param test: KVM test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def mirror_bridge_to_tap(tap_name):
        """
        Mirror all packages on bridge to tap device connected to vm vNIC

        :param tap_name: name of tap connected to vm
        """

        tc_qdisc_add_ingress = params.get("tc_qdisc_add_ingress")
        tc_filter_show_dev = params.get("tc_filter_show_dev")
        tc_filter_replace_dev = params.get("tc_filter_replace_dev") % tap_name
        tc_qdisc_replace = params.get("tc_qdisc_replace")
        process.system_output(tc_qdisc_add_ingress)
        process.system_output(tc_filter_show_dev)
        process.system_output(tc_filter_replace_dev)
        process.system_output(tc_qdisc_replace)

        tc_qdisc_show_dev = params.get("tc_qdisc_show_dev")
        output = process.system_output(tc_qdisc_show_dev).decode()
        port = re.findall("qdisc prio (.*):", output)[0]

        tc_filter_show_dev_port = params.get("tc_filter_show_dev_port") % port
        tc_filter_replace_dev_port = params.get("tc_filter_replace_dev_port") % (
            port,
            tap_name,
        )
        process.system_output(tc_filter_show_dev_port)
        process.system_output(tc_filter_replace_dev_port)

    def check_tcpdump(output, src_ip, des_ip, ping_count):
        """
        Check tcpdump result.

        :parm output: string of tcpdump output.
        :parm src_ip: ip to ping
        :parm des_ip: ip to receive ping
        :parm ping_count: total ping packets number

        :return: bool type result.
        """
        rex_request = r".*IP %s > %s.*ICMP echo request.*" % (src_ip, des_ip)
        rex_reply = r".*IP %s > %s.*ICMP echo reply.*" % (des_ip, src_ip)
        request_num = 0
        reply_num = 0
        for idx, _ in enumerate(output.splitlines()):
            if re.match(rex_request, _):
                request_num += 1
            elif re.match(rex_reply, _):
                reply_num += 1

        if request_num != ping_count or reply_num != ping_count:
            test.log.debug(
                "Unexpected request or reply number. "
                "current request number is: %d, "
                "current reply number is: %d, "
                "expected request and reply number is: %d. ",
                request_num,
                reply_num,
                ping_count,
            )
            return False
        return True

    netdst = params.get("netdst", "switch")
    br_backend = utils_net.find_bridge_manager(netdst)
    if not isinstance(br_backend, utils_net.Bridge):
        test.cancel("Host does not use Linux Bridge")

    brname = params.get("private_bridge", "tmpbr")
    net_mask = params.get("net_mask", "24")
    login_timeout = int(params.get("login_timeout", "600"))
    stop_NM_cmd = params.get("stop_NM_cmd")
    stop_firewall_cmd = params.get("stop_firewall_cmd")
    tcpdump_cmd = params.get("tcpdump_cmd")
    tcpdump_log = params.get("tcpdump_log")
    get_tcpdump_log_cmd = params.get("get_tcpdump_log_cmd")
    ping_count = int(params.get("ping_count"))

    error_context.context("Create a private bridge", test.log.info)
    br_backend.add_bridge(brname)
    br_iface = utils_net.Interface(brname)
    br_iface.up()
    br_iface.promisc_on()

    params["netdst"] = brname
    params["start_vm"] = "yes"
    vm_names = params.get("vms").split()
    vms_info = {}
    try:
        for vm_name in vm_names:
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            ip = params["ip_%s" % vm_name]
            mac = vm.get_mac_address()
            serial_session = vm.wait_for_serial_login(timeout=login_timeout)
            serial_session.cmd_output_safe(stop_NM_cmd)
            serial_session.cmd_output_safe(stop_firewall_cmd)
            nic_name = utils_net.get_linux_ifname(serial_session, mac)
            ifname = vm.get_ifname()
            ifset_cmd = "ip addr add %s/%s dev %s" % (ip, net_mask, nic_name)
            ifup_cmd = "ip link set dev %s up" % nic_name
            serial_session.cmd_output_safe(ifset_cmd)
            serial_session.cmd_output_safe(ifup_cmd)
            vms_info[vm_name] = [vm, ifname, ip, serial_session, nic_name]

        vm_mirror = vm_names[0]
        vm_src = vm_names[1]
        vm_des = vm_names[2]

        error_context.context(
            "Mirror all packets on bridge to tap device conncted to %s" % vm_mirror
        )
        tap_ifname = vms_info[vm_mirror][0].virtnet[0].ifname
        mirror_bridge_to_tap(tap_ifname)

        error_context.context("Start tcpdump in %s" % vm_mirror, test.log.info)
        tcpdump_cmd = tcpdump_cmd % (vms_info[vm_des][2], tcpdump_log)
        test.log.info("tcpdump command: %s", tcpdump_cmd)
        vms_info[vm_mirror][3].sendline(tcpdump_cmd)
        time.sleep(5)

        error_context.context(
            "Start ping from %s to %s" % (vm_src, vm_des), test.log.info
        )
        ping_cmd = params.get("ping_cmd") % vms_info[vm_des][2]
        vms_info[vm_src][3].cmd(ping_cmd, timeout=150)

        error_context.context("Check tcpdump results", test.log.info)
        time.sleep(5)
        vms_info[vm_mirror][3].cmd_output_safe("pkill tcpdump")
        tcpdump_content = vms_info[vm_mirror][3].cmd_output(get_tcpdump_log_cmd).strip()
        if not check_tcpdump(
            tcpdump_content, vms_info[vm_src][2], vms_info[vm_des][2], ping_count
        ):
            test.fail("tcpdump results are not expected, mirror fail.")
    finally:
        for vm in vms_info:
            vms_info[vm][0].destroy(gracefully=False)

        br_iface.down()
        br_backend.del_bridge(brname)
