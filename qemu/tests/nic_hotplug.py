import logging
import random

from avocado.utils import process

from virttest import utils_test
from virttest import utils_net
from virttest import virt_vm
from virttest import utils_misc


def run(test, params, env):
    """
    Test hotplug of NIC devices

    1) Boot up guest with one or multi nics
    2) Add multi host network devices through monitor cmd and
       check if they are added
    3) Add multi nic devices through monitor cmd and check if they are added
    4) Check if new interface gets ip address
    5) Disable primary link of guest, if test hot-plug nic with the netdev
       already used, then no need to disable it, hot-plug the device directly.
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
                test.error(
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
        arps = process.system_output("arp -aen")
        logging.debug("Can't get IP address:")
        logging.debug("\tCached IP: %s", cached_ip)
        logging.debug("\tARP table: %s", arps)
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

    def device_add_nic(pci_model, netdev, device_id):
        """
        call device_add command, with param device_id, driver and netdev
        :param pci_model: drivers for virtual device
        :param netdev: netdev id for virtual device
        :param device_id: device id for virtual device
        """
        pci_add_cmd = "device_add id=%s, driver=%s, netdev=%s" % (device_id,
                                                                  pci_model,
                                                                  netdev)
        add_output = vm.monitor.send_args_cmd(pci_add_cmd)
        return add_output

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
        for nic_index in range(1, nic_hotplug_count + 1):
            # need to reconnect serial port after
            # guest reboot for windows guest
            s_session = vm.wait_for_serial_login(timeout=login_timeout)
            nic_name = "hotplug_nic%s" % nic_index
            nic_params = params.object_params(nic_name)
            nic_model = nic_params["pci_model"]
            nic_params["nic_model"] = nic_model
            nic_params["nic_name"] = nic_name
            used_sameid = params.get("used_sameid")

            if used_sameid == "yes":
                useddevice_id = primary_nic[0].netdev_id
                logging.info("Hot-plug NIC with the netdev already in use")
                try:
                    add_output = device_add_nic(nic_model, useddevice_id, nic_name)
                except Exception as err_msg:
                    match_error = params["devadd_match_string"]
                    if match_error in str(err_msg):
                        s_session.close()
                        return
                    else:
                        test.fail("Hot-plug error message is not as expected: "
                                  "%s" % str(err_msg))
                else:
                    test.fail("Qemu should failed hot-plugging nic with error")
            else:
                logging.info("Disable other link(s) of guest")
                disable_nic_list = primary_nic + nic_hotplugged
                for nic in disable_nic_list:
                    if guest_is_linux:
                        ifname = utils_net.get_linux_ifname(s_session, nic["mac"])
                        s_session.cmd_output_safe("ifconfig %s 0.0.0.0" % ifname)
                    else:
                        s_session.cmd_output_safe("ipconfig /release all")
                    vm.set_link(nic.device_id, up=False)

            logging.debug("Hotplug %sth '%s' nic named '%s'",
                          nic_index, nic_model, nic_name)
            hotplug_nic = vm.hotplug_nic(**nic_params)
            logging.info("Check if new interface gets ip address")
            hotnic_ip = get_hotplug_nic_ip(
                vm,
                hotplug_nic,
                s_session,
                guest_is_linux)
            if not hotnic_ip:
                test.fail("Hotplug nic can not get ip address")
            logging.info("Got the ip address of new nic: %s", hotnic_ip)

            logging.info("Ping guest's new ip from host")
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test, error info: '%s'"
                test.fail(err_msg % output)

            logging.info("Reboot vm after hotplug nic")
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
                test.fail(
                    "Hotplug nic can't get ip after reboot vm")

            logging.info("Ping guest's new ip from host")
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test, error info: '%s'"
                test.fail(err_msg % output)

            logging.info("Pause vm")
            vm.pause()
            logging.info("Resume vm")
            vm.resume()
            logging.info("Ping guest's new ip after resume")
            status, output = ping_hotplug_nic(host_ip_addr, hotplug_nic["mac"],
                                              s_session, guest_is_linux)
            if status:
                err_msg = "New nic failed ping test after stop/cont, "
                err_msg += "error info: '%s'" % output
                test.fail(err_msg)

            # random hotunplug nic
            nic_hotplugged.append(hotplug_nic)
            if random.randint(0, 1) and params.get("do_random_unhotplug"):
                logging.info("Detaching the previously attached nic from vm")
                unplug_nic_index = random.randint(0, len(nic_hotplugged) - 1)
                vm.hotunplug_nic(nic_hotplugged[unplug_nic_index].nic_name)
                nic_hotplugged.pop(unplug_nic_index)
                s_session = vm.reboot(session=s_session, serial=True)
                vm.verify_alive()
            s_session.close()
    finally:
        for nic in nic_hotplugged:
            vm.hotunplug_nic(nic.nic_name)
        logging.info("Re-enabling the primary link(s)")
        for nic in primary_nic:
            vm.set_link(nic.device_id, up=True)
        logging.info("Reboot vm to verify it alive after hotunplug nic(s)")
        serial = not (len(vm.virtnet) > 0)
        session = vm.reboot(serial=serial)
        vm.verify_alive()
        session.close()
