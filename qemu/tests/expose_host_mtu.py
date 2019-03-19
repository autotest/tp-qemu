import logging
import re

from avocado.utils import process
from virttest import error_context
from virttest import utils_net
from virttest import utils_test
from virttest import env_process


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

    def get_ovs_ports(ovs):
        """
        Get ovs ports

        :param ovs: ovs bridge name
        """

        cmd = "ovs-vsctl list-ports %s" % ovs
        return process.system_output(cmd, shell=True).decode()

    def is_ovs_backend(netdst):
        """
        Check whether the host is OVS backend

        :param netdst: netdst get from command line
        """

        return netdst in process.system_output("ovs-vsctl list-br",
                                               ignore_status=True,
                                               shell=True).decode()

    def cleanup_ovs_ports(netdst, ports):
        """
        Clean up created ovs ports in this case

        :param netdst: netdst get from command line
        :param ports: existing ports need to be remain before this test
        """

        if is_ovs_backend(netdst) is True:
            ports = set(get_ovs_ports(netdst).splitlines()) - \
                set(ports.splitlines())
            for p in ports:
                process.system("ovs-vsctl del-port %s %s" % (netdst, p))

    netdst = params.get("netdst", "switch")
    if netdst in utils_net.Bridge().list_br():
        host_hw_interface = utils_net.Bridge().list_iface(netdst)[0]
    elif is_ovs_backend(netdst) is True:
        host_hw_interface = get_ovs_ports(netdst)
        tmp_ports = re.findall(r"t[0-9]{1,}-[a-zA-Z0-9]{6}", host_hw_interface)
        if tmp_ports:
            for p in tmp_ports:
                process.system_output("ovs-vsctl del-port %s %s" %
                                      (netdst, p))
            host_hw_interface = get_ovs_ports(netdst)
    else:
        test.cancel("The host is using Macvtap backend, which is not"
                    " supported by now!")

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm_iface = vm.get_ifname()
    # TODO, will support windows later
    process.system_output(params["set_mtu_cmd"] % host_hw_interface)
    process.system_output(params["set_mtu_cmd"] % vm_iface)

    os_type = params.get("os_type", "linux")
    login_timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    host_ip = utils_net.get_ip_address_by_interface(params["netdst"])
    if os_type == "linux":  # TODO, will support windows later
        session.cmd_output_safe(params["nm_stop_cmd"])
        guest_ifname = utils_net.get_linux_ifname(session,
                                                  vm.get_mac_address())
        output = session.cmd_output_safe(
            params["check_guest_mtu_cmd"] % guest_ifname)
        error_context.context(output, logging.info)
        match_string = "mtu %s" % params["mtu_value"]
        if match_string in output:
            logging.info("Host mtu %s exposed to guest as expected!" %
                         params["mtu_value"])
            logging.info("Ping from guest to host with packet size 3972")
            status, output = utils_test.ping(host_ip, 10, packetsize=3972,
                                             timeout=30, session=session)
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                test.fail("Loss ratio is %s", ratio)
        else:
            test.fail("host mtu %s not exposed to guest" % params["mtu_value"])
    cleanup_ovs_ports(netdst, host_hw_interface)
    session.close()
