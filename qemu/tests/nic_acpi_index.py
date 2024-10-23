import random
import re

from avocado.utils import process
from virttest import error_context, utils_misc, utils_net, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    When "acpi-index=N" is enabled, NIC name should always be "ethN"

    1) Boot up guest without nic,remove "biosdevname=0" and "net.ifname=0" from
    kenrel command line, then reboot guest.
    2) Hotplug the nic with acpi-index=N
    3) Check the nic name, the guest nic name enoN == acpi-index=N
    4) Check if new interface gets ip address
    5) Ping guest new ip from host
    6) Repeat steps 2~5 5 times

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def renew_ip_address(session, mac):
        ifname = utils_net.get_linux_ifname(session, mac)
        make_conf = (
            "nmcli connection add type ethernet con-name %s ifname "
            "%s autoconnect yes" % (ifname, ifname)
        )
        arp_clean = "arp -n|awk '/^[1-9]/{print \"arp -d \" $1}'|sh"
        session.cmd_output_safe(make_conf)
        session.cmd_output_safe("ip link set dev %s up" % ifname)
        dhcp_cmd = params.get("dhcp_cmd")
        session.cmd_output_safe(dhcp_cmd % ifname, timeout=240)
        session.cmd_output_safe(arp_clean)

    def verified_nic_name():
        ifname = utils_net.get_linux_ifname(session, vm.get_mac_address())
        pattern = int(re.findall(r"\d+", ifname)[-1])
        nic_name_number = params.get_numeric("nic_name_number")
        if pattern == nic_name_number:
            test.log.info("nic name match")
        else:
            test.fail("nic name doesn't match")

    def ping_test():
        host_ip = utils_net.get_host_ip_address(params)
        status, output = utils_net.ping(host_ip, 10, timeout=30)
        if status:
            test.fail("%s ping %s unexpected, output %s" % (vm.name, host_ip, output))

    def get_hotplug_nic_ip(vm, nic, session):
        def _get_address():
            try:
                index = [_idx for _idx, _nic in enumerate(vm.virtnet) if _nic == nic][0]
                return vm.wait_for_get_address(index, timeout=90)
            except IndexError:
                test.error(
                    "Nic '%s' not exists in VM '%s'" % (nic["nic_name"], vm.name)
                )
            except (
                virt_vm.VMIPAddressMissingError,
                virt_vm.VMAddressVerificationError,
            ):
                renew_ip_address(session, nic["mac"])
            return

        nic_ip = utils_misc.wait_for(_get_address, timeout=360)
        if nic_ip:
            return nic_ip
        cached_ip = vm.address_cache.get(nic["mac"])
        arps = process.system_output("arp -aen").decode()
        test.log.debug("Can't get IP address:")
        test.log.debug("\tCached IP: %s", cached_ip)
        test.log.debug("\tARP table: %s", arps)

    login_timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 1))
    test.log.info("repeat_times: %s", repeat_times)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)

    for iteration in range(repeat_times):
        error_context.context(
            "Start test iteration %s" % (iteration + 1), test.log.info
        )
        nic_hotplug_count = int(params.get("nic_hotplug_count", 1))
        nic_hotplugged = []
        for nic_index in range(1, nic_hotplug_count + 1):
            s_session = vm.wait_for_serial_login(timeout=login_timeout)
            nic_name = "hotplug_nic%s" % nic_index
            nic_params = params.object_params(nic_name)
            nic_model = nic_params["nic_model"]
            nic_params["nic_model"] = nic_model
            hotplug_nic = vm.hotplug_nic(**nic_params)
            test.log.info("Check if new interface gets ip address")
            hotnic_ip = get_hotplug_nic_ip(vm, hotplug_nic, s_session)

            if not hotnic_ip:
                test.log.info("Reboot vm after hotplug nic")
                # reboot vm via serial port since some guest can't auto up
                # hotplug nic and next step will check is hotplug nic works.
                s_session = vm.reboot(session=s_session, serial=True)
                vm.verify_alive()
                hotnic_ip = get_hotplug_nic_ip(vm, hotplug_nic, s_session)
                if not hotnic_ip:
                    test.fail("Hotplug nic still can't get ip after reboot vm")
            test.log.info("Got the ip address of new nic: %s", hotnic_ip)
            test.log.info("Check the nic name from inside guest")
            verified_nic_name()
            test.log.info("Ping host from guest's new ip")
            ping_test()

            # random hotunplug nic
            nic_hotplugged.append(hotplug_nic)
            if random.randint(0, 1) and params.get("do_random_unhotplug"):
                test.log.info("Detaching the previously attached nic from vm")
                unplug_nic_index = random.randint(0, len(nic_hotplugged) - 1)
                vm.hotunplug_nic(nic_hotplugged[unplug_nic_index].nic_name)
                nic_hotplugged.pop(unplug_nic_index)
                s_session = vm.reboot(session=s_session, serial=True)
                vm.verify_alive()
            s_session.close()

        for nic in nic_hotplugged:
            vm.hotunplug_nic(nic.nic_name)
