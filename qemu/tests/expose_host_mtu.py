import re

from avocado.utils.network.hosts import LocalHost
from avocado.utils.network.interfaces import NetworkInterface
from virttest import env_process, error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Expose host MTU to guest test

    1) Boot up guest with param 'host_mtu=4000' in nic part
    2) Disable NetworkManager in guest
    3) set mtu of guest tap (eg: tap0) and physical nic (eg: eno1) to
       4000 in host
    4) check the mtu in guest
    5) ping from guest to external host with packet size 3972

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def cleanup_ovs_ports(netdst, ports):
        """
        Clean up created ovs ports in this case

        :param netdst: netdst get from command line
        :param ports: existing ports need to be remain before this test
        """

        host_bridge = utils_net.find_bridge_manager(netdst)
        if utils_net.ovs_br_exists(netdst) is True:
            ports = set(host_bridge.list_ports(netdst)) - set(ports)
            for p in ports:
                utils_net.find_bridge_manager(netdst).del_port(netdst, p)

    netdst = params.get("netdst", "switch")
    mtu_value = params.get_numeric("mtu_value")
    host_bridge = utils_net.find_bridge_manager(netdst)
    localhost = LocalHost()
    try:
        if netdst in utils_net.Bridge().list_br():
            host_hw_interface = utils_net.Bridge().list_iface(netdst)[0]
        else:
            host_hw_interface = host_bridge.list_ports(netdst)
            tmp_ports = re.findall(
                r"t[0-9]{1,}-[a-zA-Z0-9]{6}", " ".join(host_hw_interface)
            )
            if tmp_ports:
                for p in tmp_ports:
                    host_bridge.del_port(netdst, p)
                host_hw_interface = host_bridge.list_ports(netdst)
    except IndexError:
        host_hw_interface = netdst

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm_iface = vm.get_ifname()
    # Get host interface original mtu value before setting
    if netdst in utils_net.Bridge().list_br():
        host_hw_iface = NetworkInterface(host_hw_interface, localhost)
    elif utils_net.ovs_br_exists(netdst) is True:
        host_hw_iface = NetworkInterface(" ".join(host_hw_interface), localhost)
    else:
        raise OSError(f"invalid host iface {netdst}")
    host_mtu_origin = host_hw_iface.get_mtu()

    NetworkInterface(vm_iface, localhost).set_mtu(mtu_value)
    host_hw_iface.set_mtu(mtu_value)

    os_type = params.get("os_type", "linux")
    login_timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    host_ip = utils_net.get_ip_address_by_interface(params["netdst"])
    if os_type == "linux":
        session.cmd_output_safe(params["nm_stop_cmd"])
        guest_ifname = utils_net.get_linux_ifname(session, vm.get_mac_address())
        output = session.cmd_output_safe(params["check_linux_mtu_cmd"] % guest_ifname)
        error_context.context(output, test.log.info)
        match_string = "mtu %s" % params["mtu_value"]
        if match_string not in output:
            test.fail("host mtu %s not exposed to guest" % params["mtu_value"])
    elif os_type == "windows":
        connection_id = utils_net.get_windows_nic_attribute(
            session, "macaddress", vm.get_mac_address(), "netconnectionid"
        )
        output = session.cmd_output_safe(params["check_win_mtu_cmd"] % connection_id)
        error_context.context(output, test.log.info)
        lines = output.strip().splitlines()
        len(lines)

        line_table = lines[0].split("  ")
        line_value = lines[2].split("  ")
        while "" in line_table:
            line_table.remove("")
        while "" in line_value:
            line_value.remove("")
        index = 0
        for name in line_table:
            if re.findall("MTU", name):
                break
            index += 1
        guest_mtu_value = line_value[index]
        test.log.info("MTU is %s", guest_mtu_value)
        if not int(guest_mtu_value) == mtu_value:
            test.fail("Host mtu %s is not exposed to " "guest!" % params["mtu_value"])

    test.log.info("Ping from guest to host with packet size 3972")
    status, output = utils_test.ping(
        host_ip, 10, packetsize=3972, timeout=30, session=session
    )
    ratio = utils_test.get_loss_ratio(output)
    if ratio != 0:
        test.fail("Loss ratio is %s", ratio)

    # Restore host mtu after finish testing
    NetworkInterface(vm_iface, localhost).set_mtu(host_mtu_origin)
    host_hw_iface.set_mtu(host_mtu_origin)

    if netdst not in utils_net.Bridge().list_br():
        cleanup_ovs_ports(netdst, host_hw_interface)
    session.close()
