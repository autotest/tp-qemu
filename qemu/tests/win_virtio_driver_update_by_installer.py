import ast
import re

from virttest import data_dir, error_context, utils_misc, utils_net

from provider import virtio_fs_utils, win_driver_installer_test, win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Create shared directories on the host.
    2) Run virtiofsd daemons on the host.
    3) Boot guest with all virtio device.
    4) Delete the virtio fs service on guest.
    5) Install driver from previous virtio-win.iso.
       Or virtio-win-guest-tool.
    6) Start virtio fs service on guest.
    7) Check for ip, gateway and dns consistency before and after
       upgrade driver
    7.1) Set static ip, additional ips, gateway and dns
    7.2) Upgrade driver via virtio-win-guest-tools.exe
    7.3) Check primary ip remains the first address (via netsh ordered
         output), gateway is preserved, additional ips still exist,
         and dns servers are preserved
    7.4) Restore NIC back to DHCP to keep network config consistent
    8) Start virtio fs service on guest.
    9) Verify the qemu-ga version match expected version.
    10) Run driver signature check command in guest.
       Verify target driver.
    11) Run driver function test after virtio-win-guest-tools.exe update.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def change_virtio_media(cdrom_virtio):
        """
        change iso for virtio-win.

        :param cdrom_virtio: iso file
        """
        virtio_iso = utils_misc.get_path(data_dir.get_data_dir(), cdrom_virtio)
        test.log.info("Changing virtio iso image to '%s'", virtio_iso)
        vm.change_media("drive_virtio", virtio_iso)

    def get_netsh_nic_info(session_serial, ifname):
        """
        Get ordered IP addresses and gateway from netsh output.
        Unlike wmic IPAddress which returns IPs in arbitrary order,
        netsh preserves the actual configured order where the first
        IP is the primary address.

        :param session_serial: serial session
        :param ifname: NIC connection name
        :return: tuple (ip_list, gateway) where ip_list is an ordered
                 list of IPv4 addresses and gateway is the default
                 gateway string (or None if not set)
        """
        cmd = params["show_addresses_cmd"] % ifname
        output = session_serial.cmd_output(cmd)
        test.log.info("netsh addresses output:\n%s", output)

        ip_list = re.findall(r"IP Address:\s+(\d+\.\d+\.\d+\.\d+)", output)
        gw_match = re.search(r"Default Gateway:\s+(\d+\.\d+\.\d+\.\d+)", output)
        gateway = gw_match.group(1) if gw_match else None
        return ip_list, gateway

    def check_network_config(session_serial):
        """
        Check ip, gateway and dns consistency after driver upgrade.
        Primary IP must remain the first address in the ordered list,
        gateway must match the configured static gateway, additional
        IPs only need to exist regardless of order, and DNS servers
        must be preserved.

        :param session_serial: session_serial
        """
        ifname = utils_net.get_windows_nic_attribute(
            session_serial, "macaddress", virtio_nic_mac, "netconnectionid"
        )

        ip_check_timeout = int(params.get("ip_check_timeout", 30))
        ip_check_interval = int(params.get("ip_check_interval", 5))

        def _get_nic_ip_list():
            ip_list, gateway = get_netsh_nic_info(session_serial, ifname)
            test.log.info(
                "Current guest IPv4 addresses (ordered): %s, gateway: %s",
                ip_list,
                gateway,
            )
            return (ip_list, gateway) if ip_list else None

        result = utils_misc.wait_for(
            _get_nic_ip_list,
            timeout=ip_check_timeout,
            step=ip_check_interval,
            text="Waiting for IPv4 address to appear on the NIC",
            first=5,
            # first=5, Wait for IP addresses to become visible in netsh output.
        )
        if not result:
            test.fail(
                "No IPv4 address found on the NIC after waiting "
                "%s seconds" % ip_check_timeout
            )
        ip_list, gateway = result

        if ip_list[0] != params["static_ip"]:
            test.fail(
                "Primary IP is not consistent, expected %s as the "
                "first address but got %s (full list: %s)"
                % (params["static_ip"], ip_list[0], ip_list)
            )

        expected_gateway = params.get("static_gateway")
        if expected_gateway:
            if gateway != expected_gateway:
                test.fail(
                    "Gateway is not consistent, expected %s but got %s"
                    % (expected_gateway, gateway)
                )

        for ip in params.get("additional_ips", "").split():
            if ip not in ip_list:
                test.fail(
                    "Additional ip %s is missing, current ips: %s" % (ip, ip_list)
                )

        static_dns_address = utils_net.get_windows_nic_attribute(
            session_serial,
            global_switch="nicconfig",
            key="MACAddress",
            value=f"{virtio_nic_mac}",
            target="DNSServerSearchOrder",
        )
        test.log.info("Current guest DNS servers: %s", static_dns_address)
        for dns in params.get("static_dns_list", "").split():
            if dns not in static_dns_address:
                test.fail(
                    "Static dns is lost after upgrade driver, current dns "
                    "is %s" % static_dns_address
                )

    def restore_network_config(session_serial):
        """
        Restore NIC network configuration back to DHCP after the
        static IP check is done, to ensure the network config is
        consistent with the original state before the test.

        :param session_serial: session_serial
        """
        ifname = utils_net.get_windows_nic_attribute(
            session_serial, "macaddress", virtio_nic_mac, "netconnectionid"
        )
        test.log.info("Restoring NIC '%s' to DHCP", ifname)
        session_serial.cmd_status(params["restore_dhcp_cmd"] % ifname)
        session_serial.cmd_status(params["restore_dns_cmd"] % ifname)
        test.log.info("NIC '%s' has been restored to DHCP", ifname)

    devcon_path = params["devcon_path"]
    run_install_cmd = params["run_install_cmd"]
    media_type = params["virtio_win_media_type"]

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    virtio_nic_mac = vm.virtnet[1].mac

    expected_gagent_version = win_driver_installer_test.install_gagent(
        session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd
    )

    win_driver_installer_test.uninstall_gagent(session, test, gagent_uninstall_cmd)

    error_context.context("Delete the viofs service at guest...")
    virtio_fs_utils.delete_viofs_serivce(test, params, session)

    win_driver_installer_test.win_uninstall_all_drivers(session, test, params)
    change_virtio_media(params["cdrom_virtio_downgrade"])

    session = vm.reboot(session)

    if params.get("update_from_previous_installer", "no") == "yes":
        error_context.context("install drivers from previous installer", test.log.info)
        session = win_driver_installer_test.run_installer_with_interaction(
            vm, session, test, params, run_install_cmd, copy_files_params=params
        )

        session_serial = vm.wait_for_serial_login()
        if vm.virtnet[1].nic_model == "virtio-net-pci":
            ifname = utils_net.get_windows_nic_attribute(
                session_serial, "macaddress", virtio_nic_mac, "netconnectionid"
            )
            setup_ip_cmd = params["setup_ip_cmd"] % ifname
            test.log.info("Setting up primary static IP: %s", params["static_ip"])
            session_serial.cmd_status(setup_ip_cmd)

            additional_ips = params.get("additional_ips", "").split()
            additional_masks = params.get("additional_masks", "").split()

            for i, ip in enumerate(additional_ips):
                mask = additional_masks[i] if i < len(additional_masks) else "255.0.0.0"
                cmd = params["add_ip_cmd"] % (ifname, ip, mask)
                test.log.info("Adding additional IP: %s with mask %s", ip, mask)
                session_serial.cmd_status(cmd)

            dns_list = params.get("static_dns_list", "").split()
            for i, dns in enumerate(dns_list):
                cmd = params["add_dns_cmd"] % (ifname, dns, i + 1)
                test.log.info("Adding DNS server: %s at index %s", dns, i + 1)
                session_serial.cmd_status(cmd)

            check_network_config(session_serial)
        session_serial.close()
    else:
        for driver_name, device_name, device_hwid in zip(
            win_driver_installer_test.driver_name_list,
            win_driver_installer_test.device_name_list,
            win_driver_installer_test.device_hwid_list,
        ):
            win_driver_utils.install_driver_by_virtio_media(
                session, test, devcon_path, media_type, driver_name, device_hwid
            )
        win_driver_installer_test.install_gagent(
            session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd
        )

    error_context.context("Run viofs service...")
    virtio_fs_utils.run_viofs_service(test, params, session)

    error_context.context("Upgrade virtio driver to original", test.log.info)
    change_virtio_media(params["cdrom_virtio"])
    session = win_driver_installer_test.run_installer_with_interaction(
        vm, session, test, params, run_install_cmd, copy_files_params=params
    )

    if params.get("update_from_previous_installer", "no") == "yes":
        session_serial = vm.wait_for_serial_login()
        check_network_config(session_serial)
        error_context.context(
            "Restore network config to DHCP after upgrade check", test.log.info
        )
        restore_network_config(session_serial)
        session_serial.close()

    error_context.context("Run viofs service after upgrade...")
    virtio_fs_utils.run_viofs_service(test, params, session)

    win_driver_installer_test.check_gagent_version(
        session, test, gagent_pkg_info_cmd, expected_gagent_version
    )
    win_driver_installer_test.driver_check(session, test, params)

    error_context.context("Run driver function test after update", test.log.info)
    fail_tests = []
    test_drivers = params.get(
        "test_drivers", win_driver_installer_test.driver_name_list
    )
    if params.get("test_drivers"):
        test_drivers = params["test_drivers"].split()
    for driver_name in test_drivers:
        test_name = params.get("driver_test_name_%s" % driver_name)
        test_func = "win_driver_installer_test.%s_test" % test_name
        driver_test_params = params.get("driver_test_params_%s" % driver_name, "{}")
        if driver_name == "balloon":
            balloon_test_win = BallooningTestWin(test, params, env)
            driver_test_params = {"balloon_test_win": balloon_test_win}
        else:
            driver_test_params = ast.literal_eval(driver_test_params)
        try:
            eval("%s(test, params, vm, **driver_test_params)" % test_func)
        except Exception as e:
            fail_tests.append("%s:\n%s" % (test_name, str(e)))
    if fail_tests:
        test.fail("Function test failed list is %s after update" % fail_tests)

    session.close()
