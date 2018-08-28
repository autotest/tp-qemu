import logging
import random

from avocado.utils import process
from virttest import utils_misc
from virttest import utils_test
from virttest import utils_net
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test the RX jumbo frame function of vnics:

    1) Boot the VM.
    2) Change the MTU of guest nics and host taps depending on the NIC model.
    3) Add the static ARP entry for guest NIC.
    4) Wait for the MTU ok.
    5) Verify the path MTU using ping.
    6) Ping the guest with large frames.
    7) Increment size ping.
    8) Flood ping the guest with large frames.
    9) Verify the path MTU.
    10) Recover the MTU.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    timeout = int(params.get("login_timeout", 360))
    mtu_default = 1500
    mtu = params.get("mtu", "1500")
    def_max_icmp_size = int(mtu) - 28
    max_icmp_pkt_size = int(params.get("max_icmp_pkt_size",
                                       def_max_icmp_size))
    flood_time = params.get("flood_time", "300")
    os_type = params.get("os_type")
    os_variant = params.get("os_variant")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    session_serial = vm.wait_for_serial_login(timeout=timeout)

    ifname = vm.get_ifname(0)
    guest_ip = vm.get_address(0)
    if guest_ip is None:
        test.error("Could not get the guest ip address")

    def get_ovs_ports(ovs):
        '''
        get the ovs bridge all Interface list.

        :param ovs: Ovs bridge name
        '''
        cmd = "ovs-vsctl list-ports %s" % ovs
        return set(process.system_output(cmd, shell=True).splitlines())

    host_mtu_cmd = "ifconfig %s mtu %s"
    netdst = params.get("netdst", "switch")
    host_bridges = utils_net.Bridge()
    br_in_use = host_bridges.list_br()
    if netdst in br_in_use:
        ifaces_in_use = host_bridges.list_iface()
        target_ifaces = set(ifaces_in_use) - set(br_in_use)
    else:
        target_ifaces = get_ovs_ports(netdst)
    error_context.context("Change all Bridge NICs MTU to %s" %
                          mtu, logging.info)
    for iface in target_ifaces:
        process.run(host_mtu_cmd % (iface, mtu), shell=True)

    try:
        error_context.context("Changing the MTU of guest", logging.info)
        # Environment preparation
        mac = vm.get_mac_address(0)
        if os_type == "linux":
            ethname = utils_net.get_linux_ifname(session, mac)
            guest_mtu_cmd = "ifconfig %s mtu %s" % (ethname, mtu)
        else:
            connection_id = utils_net.get_windows_nic_attribute(
                session, "macaddress", mac, "netconnectionid")

            index = utils_net.get_windows_nic_attribute(
                session, "netconnectionid", connection_id, "index")
            if os_variant == "winxp":
                pnpdevice_id = utils_net.get_windows_nic_attribute(
                    session, "netconnectionid", connection_id, "pnpdeviceid")
                cd_num = utils_misc.get_winutils_vol(session)
                copy_cmd = r"xcopy %s:\devcon\wxp_x86\devcon.exe c:\ " % cd_num
                session.cmd(copy_cmd)

            reg_set_mtu_pattern = params.get("reg_mtu_cmd")
            mtu_key_word = params.get("mtu_key", "MTU")
            reg_set_mtu = reg_set_mtu_pattern % (int(index), mtu_key_word,
                                                 int(mtu))
            guest_mtu_cmd = "%s " % reg_set_mtu

        session.cmd(guest_mtu_cmd)
        if os_type == "windows":
            mode = "netsh"
            if os_variant == "winxp":
                connection_id = pnpdevice_id.split("&")[-1]
                mode = "devcon"
            utils_net.restart_windows_guest_network(session_serial,
                                                    connection_id,
                                                    mode=mode)

        error_context.context("Chaning the MTU of host tap ...", logging.info)
        host_mtu_cmd = "ifconfig %s mtu %s"
        # Before change macvtap mtu, must set the base interface mtu
        if params.get("nettype") == "macvtap":
            base_if = utils_net.get_macvtap_base_iface(params.get("netdst"))
            process.run(host_mtu_cmd % (base_if, mtu), shell=True)
        process.run(host_mtu_cmd % (ifname, mtu), shell=True)

        error_context.context("Add a temporary static ARP entry ...",
                              logging.info)
        arp_add_cmd = "arp -s %s %s -i %s" % (guest_ip, mac, ifname)
        process.run(arp_add_cmd, shell=True)

        def is_mtu_ok():
            status, _ = utils_test.ping(guest_ip, 1,
                                        packetsize=max_icmp_pkt_size,
                                        hint="do", timeout=2)
            return status == 0

        def verify_mtu():
            logging.info("Verify the path MTU")
            status, output = utils_test.ping(guest_ip, 10,
                                             packetsize=max_icmp_pkt_size,
                                             hint="do", timeout=15)
            if status != 0:
                logging.error(output)
                test.fail("Path MTU is not as expected")
            if utils_test.get_loss_ratio(output) != 0:
                logging.error(output)
                test.fail("Packet loss ratio during MTU "
                          "verification is not zero")

        def flood_ping():
            logging.info("Flood with large frames")
            utils_test.ping(guest_ip,
                            packetsize=max_icmp_pkt_size,
                            flood=True, timeout=float(flood_time))

        def large_frame_ping(count=100):
            logging.info("Large frame ping")
            _, output = utils_test.ping(guest_ip, count,
                                        packetsize=max_icmp_pkt_size,
                                        timeout=float(count) * 2)
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                test.fail("Loss ratio of large frame ping is %s" % ratio)

        def size_increase_ping(step=random.randrange(90, 110)):
            logging.info("Size increase ping")
            for size in range(0, max_icmp_pkt_size + 1, step):
                logging.info("Ping %s with size %s", guest_ip, size)
                status, output = utils_test.ping(guest_ip, 1,
                                                 packetsize=size,
                                                 hint="do", timeout=1)
                if status != 0:
                    status, output = utils_test.ping(guest_ip, 10,
                                                     packetsize=size,
                                                     adaptive=True,
                                                     hint="do",
                                                     timeout=20)

                    fail_ratio = int(params.get("fail_ratio", 50))
                    if utils_test.get_loss_ratio(output) > fail_ratio:
                        test.fail("Ping loss ratio is greater "
                                  "than 50% for size %s" % size)

        logging.info("Waiting for the MTU to be OK")
        wait_mtu_ok = 10
        if not utils_misc.wait_for(is_mtu_ok, wait_mtu_ok, 0, 1):
            logging.debug(process.system_output("ifconfig -a",
                          verbose=False, ignore_status=True,
                          shell=True))
            test.error("MTU is not as expected even after %s "
                       "seconds" % wait_mtu_ok)

        # Functional Test
        error_context.context("Checking whether MTU change is ok",
                              logging.info)
        verify_mtu()
        large_frame_ping()
        size_increase_ping()

        # Stress test
        flood_ping()
        verify_mtu()

    finally:
        # Environment clean
        if session:
            session.close()
        grep_cmd = "grep '%s.*%s' /proc/net/arp" % (guest_ip, ifname)
        if process.system(grep_cmd, shell=True) == '0':
            process.run("arp -d %s -i %s" % (guest_ip, ifname),
                        shell=True)
            logging.info("Removing the temporary ARP entry successfully")

        logging.info("Change back Bridge NICs MTU to %s" % mtu_default)
        for iface in target_ifaces:
            process.run(host_mtu_cmd % (iface, mtu_default), shell=True)
