import logging
import random

from autotest.client.shared import error
from autotest.client.shared import utils

from virttest import utils_test
from virttest import utils_net
from virttest import virt_vm
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    Test hotplug of NIC devices

    1) Boot up guest with one or multi nics
    2) Add multi host network devices through monitor cmd and
       check if they are added
    3) Add multi nic devices through monitor cmd and check if they are added
    4) Check if new interface gets ip address
    5) Disable primary link of guest
    6) Ping guest new ip from host
    7) Delete nic device and netdev if user config "do_random_unhotplug"
    8) Ping guest's new ip address after guest pause/resume
    9) Re-enable primary link of guest and hotunplug the plug nics

    BEWARE OF THE NETWORK BRIDGE DEVICE USED FOR THIS TEST ("nettype=bridge"
    and "netdst=<bridgename>" param).  The virt-test default bridge virbr0,
    leveraging libvirt, works fine for the purpose of this test. When using
    other bridges, the timeouts which usually happen when the bridge
    topology changes (that is, devices get added and removed) may cause random
    failures.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def renew_ip_address(session, mac, is_linux_guest=True):
        if not is_linux_guest:
            utils_net.restart_windows_guest_network_by_key(session,
                                                           "macaddress",
                                                           mac)
            return None
        ifname = utils_net.get_linux_ifname(session, mac)
        p_cfg = "/etc/sysconfig/network-scripts/ifcfg-%s" % ifname
        cfg_con = "DEVICE=%s\nBOOTPROTO=dhcp\nONBOOT=yes" % ifname
        make_conf = "test -f %s || echo '%s' > %s" % (p_cfg, cfg_con, p_cfg)
        arp_clean = "arp -n|awk '/^[1-9]/{print \"arp -d \" $1}'|sh"
        session.cmd_output_safe(make_conf)
        session.cmd_output_safe("ifconfig %s up" % ifname)
        session.cmd_output_safe("dhclient -r", timeout=240)
        session.cmd_output_safe("dhclient %s" % ifname, timeout=240)
        session.cmd_output_safe(arp_clean)
        return None

    def get_hotplug_nic_ip(vm, nic, session, is_linux_guest=True):
        def __get_address():
            try:
                index = [
                    _idx for _idx, _nic in enumerate(
                        vm.virtnet) if _nic == nic][0]
                return vm.wait_for_get_address(index, timeout=90)
            except IndexError:
                raise error.TestError(
                    "Nic '%s' not exists in VM '%s'" %
                    (nic["nic_name"], vm.name))
            except (virt_vm.VMIPAddressMissingError,
                    virt_vm.VMAddressVerificationError):
                renew_ip_address(session, nic["mac"], is_linux_guest)
            return

        nic_ip = utils_misc.wait_for(__get_address, timeout=360)
        if nic_ip:
            return nic_ip
        cached_ip = vm.address_cache.get(nic["mac"])
        arps = utils.system_output("arp -aen")
        logging.debug("Can't get IP address:")
        logging.debug("\tCached IP: %s" % cached_ip)
        logging.debug("\tARP table: %s" % arps)
        return None

    def ping_hotplug_nic(ip, mac, session, is_linux_guest):
        status, output = utils_test.ping(ip, 10, timeout=30)
        if status != 0:
            if not is_linux_guest:
                return status, output
            ifname = utils_net.get_linux_ifname(session, mac)
            add_route_cmd = "route add %s dev %s" % (ip, ifname)
            del_route_cmd = "route del %s dev %s" % (ip, ifname)
            logging.warn("Failed to ping %s from host.")
            logging.info("Add route and try again")
            session.cmd_output_safe(add_route_cmd)
            status, output = utils_test.ping(hotnic_ip, 10, timeout=30)
            logging.info("Del the route.")
            status, output = session.cmd_output_safe(del_route_cmd)
        return status, output

    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    primary_nic = [nic for nic in vm.virtnet]
    guest_is_linux = ("linux" == params.get("os_type", ""))
    host_ip_addr = utils_net.get_host_ip_address(params)
    if guest_is_linux:
        # Modprobe the module if specified in config file
        module = params.get("modprobe_module")
        if module:
            s_session = vm.wait_for_serial_login(timeout=login_timeout)
            s_session.cmd_output_safe("modprobe %s" % module)
            s_session.close()
    nic_hotplug_count = int(params.get("nic_hotplug_count", 1))
    nic_hotplugged = []
    try:
        for nic_index in xrange(1, nic_hotplug_count + 1):
            # need to reconnect serial port after
            # guest reboot for windows guest
            s_session = vm.wait_for_serial_login(timeout=login_timeout)
            nic_name = "hotplug_nic%s" % nic_index
            nic_params = params.object_params(nic_name)
            nic_model = nic_params["pci_model"]
            nic_params["nic_model"] = nic_model
            nic_params["nic_name"] = nic_name

            error.context("Disable other link(s) of guest", logging.info)
            disable_nic_list = primary_nic + nic_hotplugged
            for nic in disable_nic_list:
                if guest_is_linux:
                    ifname = utils_net.get_linux_ifname(s_session, nic["mac"])
                    s_session.cmd_output_safe("ifconfig %s 0.0.0.0" % ifname)
                else:
                    s_session.cmd_output_safe("ipconfig /release all")
                vm.set_link(nic.device_id, up=False)

            error.context("Hotplug %sth '%s' nic named '%s'" % (nic_index,
                                                                nic_model,
                                                                nic_name))
            hotplug_nic = vm.hotplug_nic(**nic_params)
            error.context("Check if new interface gets ip address",
                          logging.info)
            hotnic_ip = get_hotplug_nic_ip(
                vm,
                hotplug_nic,
                s_session,
                guest_is_linux)
            if not hotnic_ip:
                raise error.TestFail("Hotplug nic can get ip address")
            logging.info("Got the ip address of new nic: %s", hotnic_ip)

            error.context("Ping guest's new ip from host", logging.info)
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test, error info: '%s'"
                raise error.TestFail(err_msg % output)

            error.context("Reboot vm after hotplug nic", logging.info)
            # reboot vm via serial port since some guest can't auto up
            # hotplug nic and next step will check is hotplug nic works.
            s_session = vm.reboot(session=s_session, serial=True)
            vm.verify_alive()
            hotnic_ip = get_hotplug_nic_ip(
                vm,
                hotplug_nic,
                s_session,
                guest_is_linux)
            if not hotnic_ip:
                raise error.TestFail(
                    "Hotplug nic can't get ip after reboot vm")

            error.context("Ping guest's new ip from host", logging.info)
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test, error info: '%s'"
                raise error.TestFail(err_msg % output)

            error.context("Pause vm", logging.info)
            vm.monitor.cmd("stop")
            vm.verify_status("paused")
            error.context("Resume vm", logging.info)
            vm.monitor.cmd("cont")
            vm.verify_status("running")
            error.context("Ping guest's new ip after resume", logging.info)
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test after stop/cont, "
                err_msg += "error info: '%s'" % output
                raise error.TestFail(err_msg)

            # random hotunplug nic
            nic_hotplugged.append(hotplug_nic)
            if random.randint(0, 1) and params.get("do_random_unhotplug"):
                error.context("Detaching the previously attached nic from vm",
                              logging.info)
                unplug_nic_index = random.randint(0, len(nic_hotplugged) - 1)
                vm.hotunplug_nic(nic_hotplugged[unplug_nic_index].nic_name)
                nic_hotplugged.pop(unplug_nic_index)
                s_session = vm.reboot(session=s_session, serial=True)
                vm.verify_alive()
            s_session.close()
    finally:
        for nic in nic_hotplugged:
            vm.hotunplug_nic(nic.nic_name)
        error.context("Re-enabling the primary link(s)", logging.info)
        for nic in primary_nic:
            vm.set_link(nic.device_id, up=True)
        error.context("Reboot vm to verify it alive after hotunplug nic(s)",
                      logging.info)
        serial = len(vm.virtnet) > 0 and False or True
        session = vm.reboot(serial=serial)
        vm.verify_alive()
        session.close()
