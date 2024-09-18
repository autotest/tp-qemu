import random
import re
import time
from ipaddress import ip_address

from avocado.utils import process
from virttest import error_context, test_setup, utils_misc, utils_net, utils_test


def check_network_interface_ip(interface, ipv6="no"):
    check_cmd = "ifconfig %s" % interface
    output = process.system_output(check_cmd)
    ip_re = r"inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    if ipv6 == "yes":
        ip_re = r"inet6 (\S+)"
    try:
        _ip = re.findall(ip_re, output)[0]
    except IndexError:
        _ip = None
    return _ip


def ifup_down_interface(test, interface, action="up"):
    check_cmd = "ifconfig %s" % interface
    output = process.system_output(check_cmd)
    if action == "up":
        if not check_network_interface_ip(interface):
            if "UP" in output.splitlines()[0]:
                process.system("ifdown %s" % interface, timeout=120, ignore_status=True)
            process.system("ifup %s" % interface, timeout=120, ignore_status=True)
    elif action == "down":
        if "UP" in output.splitlines()[0]:
            process.system("ifdown %s" % interface, timeout=120, ignore_status=True)
    else:
        msg = "Unsupport action '%s' on network interface." % action
        test.error(msg)


@error_context.context_aware
def run(test, params, env):
    """
    SR-IOV devices sanity test:
    1) Bring up VFs by following instructions How To in Setup.
    2) Configure all VFs in host.
    3) Check whether all VFs get ip in host.
    4) Unbind PFs/VFs from host kernel driver to sr-iov driver.
    5) Bind PFs/VFs back to host kernel driver.
    6) Repeat step 4, 5.
    7) Try to boot up guest(s) with VF(s).

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    device_driver = params.get("device_driver", "pci-assign")
    repeat_time = int(params.get("bind_repeat_time", 1))
    configure_on_host = int(params.get("configure_on_host", 0))
    static_ip = int(params.get("static_ip", 1))
    serial_login = params.get("serial_login", "no")
    pci_assignable = test_setup.PciAssignable(
        driver=params.get("driver"),
        driver_option=params.get("driver_option"),
        host_set_flag=params.get("host_set_flag", 1),
        kvm_params=params.get("kvm_default"),
        vf_filter_re=params.get("vf_filter_re"),
        pf_filter_re=params.get("pf_filter_re"),
        device_driver=device_driver,
        pa_type=params.get("pci_assignable"),
        static_ip=static_ip,
        net_mask=params.get("net_mask"),
        start_addr_PF=params.get("start_addr_PF"),
    )

    devices = []
    device_type = params.get("device_type", "vf")
    if device_type == "vf":
        device_num = pci_assignable.get_vfs_count()
        if device_num == 0:
            msg = " No VF device found even after running SR-IOV setup"
            test.cancel(msg)
    elif device_type == "pf":
        device_num = len(pci_assignable.get_pf_vf_info())
    else:
        msg = "Unsupport device type '%s'." % device_type
        msg += " Please set device_type to 'vf' or 'pf'."
        test.error(msg)

    for i in range(device_num):
        device = {}
        device["type"] = device_type
        if device_type == "vf":
            device["mac"] = utils_net.generate_mac_address_simple()
        if params.get("device_name"):
            device["name"] = params.get("device_name")
        devices.append(device)

    pci_assignable.devices = devices
    vf_pci_id = []
    pf_vf_dict = pci_assignable.get_pf_vf_info()
    for pf_dict in pf_vf_dict:
        vf_pci_id.extend(pf_dict["vf_ids"])

    ethname_dict = []
    ips = {}

    # Not all test environments would have a dhcp server to serve IP for
    # all mac addresses. So configure_on_host param has been
    # introduced to choose whether configure VFs on host or not
    if configure_on_host:
        msg = "Configure all VFs in host."
        error_context.context(msg, test.log.info)
        for pci_id in vf_pci_id:
            ethname = utils_misc.get_interface_from_pci_id(pci_id)
            mac = utils_net.generate_mac_address_simple()
            ethname_dict.append(ethname)
            # TODO:cleanup of the network scripts
            try:
                utils_net.create_network_script(
                    ethname, mac, "dhcp", "255.255.255.0", on_boot="yes"
                )
            except Exception as info:
                test.error("Network script creation failed - %s" % info)

        msg = "Check whether VFs could get ip in host."
        error_context.context(msg, test.log.info)
        for ethname in ethname_dict:
            utils_net.bring_down_ifname(ethname)
            _ip = check_network_interface_ip(ethname)
            if not _ip:
                msg = "Interface '%s' could not get IP." % ethname
                test.log.error(msg)
            else:
                ips[ethname] = _ip
                test.log.info("Interface '%s' get IP '%s'", ethname, _ip)

    for i in range(repeat_time):
        msg = "Bind/unbind device from host. Repeat %s/%s" % (i + 1, repeat_time)
        error_context.context(msg, test.log.info)
        bind_device_num = random.randint(1, device_num)
        pci_assignable.request_devs(devices[:bind_device_num])
        test.log.info("Sleep 3s before releasing vf to host.")
        time.sleep(3)
        pci_assignable.release_devs()
        test.log.info("Sleep 3s after releasing vf to host.")
        time.sleep(3)
        if device_type == "vf":
            post_device_num = pci_assignable.get_vfs_count()
        else:
            post_device_num = len(pci_assignable.get_pf_vf_info())
        if post_device_num != device_num:
            msg = "lspci cannot report the correct PF/VF number."
            msg += " Correct number is '%s'" % device_num
            msg += " lspci report '%s'" % post_device_num
            test.fail(msg)
    dmesg = process.system_output("dmesg")
    file_name = "host_dmesg_after_unbind_device.txt"
    test.log.info("Log dmesg after bind/unbing device to '%s'.", file_name)
    if configure_on_host:
        msg = "Check whether VFs still get ip in host."
        error_context.context(msg, test.log.info)
        for ethname in ips:
            utils_net.bring_up_ifname(ethname)
            _ip = utils_net.get_ip_address_by_interface(ethname, ip_ver="ipv4")
            if not _ip:
                msg = "Interface '%s' could not get IP." % ethname
                msg += "Before bind/unbind it have IP '%s'." % ips[ethname]
                test.log.error(msg)
            else:
                test.log.info("Interface '%s' get IP '%s'", ethname, _ip)

    msg = "Try to boot up guest(s) with VF(s)."
    error_context.context(msg, test.log.info)
    regain_ip_cmd = params.get("regain_ip_cmd", None)
    timeout = int(params.get("login_timeout", 30))

    for vm_name in params["vms"].split(" "):
        params["start_vm"] = "yes"
        vm = env.get_vm(vm_name)
        # User can opt for dhcp IP or a static IP configuration for probed
        # interfaces inside guest. Added option for static IP configuration
        # below
        if static_ip:
            IP_addr_VF = None
            if "IP_addr_VF" not in locals():
                IP_addr_VF = ip_address(params.get("start_addr_VF"))
                net_mask = params.get("net_mask")
            if not IP_addr_VF:
                test.fail(
                    "No IP address found, please"
                    "populate starting IP address in "
                    "configuration file"
                )
            session = vm.wait_for_serial_login(
                timeout=int(params.get("login_timeout", 720))
            )
            rc, output = session.cmd_status_output(
                "ip li| grep -i 'BROADCAST'|awk '{print $2}'| sed 's/://'"
            )
            if not rc:
                iface_probed = output.splitlines()
                test.log.info("probed VF Interface(s) in guest: %s", iface_probed)
                for iface in iface_probed:
                    mac = utils_net.get_linux_mac(session, iface)
                    utils_net.set_guest_ip_addr(session, mac, IP_addr_VF)
                    rc, output = utils_test.ping(str(IP_addr_VF), 30, timeout=60)
                    if rc != 0:
                        test.fail(
                            "New nic failed ping test" "with output:\n %s" % output
                        )
                    IP_addr_VF = IP_addr_VF + 1
            else:
                test.fail(
                    "Fail to locate probed interfaces"
                    "for VFs, please check on respective"
                    "drivers in guest image"
                )
        else:
            # User has opted for DHCP IP inside guest
            vm.verify_alive()
            vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
