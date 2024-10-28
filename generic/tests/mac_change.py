import re

from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def check_guest_mac(test, mac, vm, device_id=None):
    """
    check mac address of guest via qmp.

    :param test: test object
    :param mac: mac address of guest
    :param vm: target vm
    :param device_id: id of network pci device
    """
    error_context.context("Check mac address via monitor", test.log.info)
    network_info = str(vm.monitor.info("network"))
    if not device_id:
        device_id = vm.virtnet[0].device_id

    if device_id not in network_info:
        err = "Could not find device '%s' from query-network monitor command.\n"
        err += "query-network command output: %s" % network_info
        test.error(err)
    if not re.search(("%s.*%s" % (device_id, mac)), network_info, re.M | re.I):
        err = "Could not get correct mac from qmp command!\n"
        err += "query-network command output: %s" % network_info
        test.fail(err)


@error_context.context_aware
def run(test, params, env):
    """
    Change MAC address of guest.

    1) Get a new mac from pool, and the old mac addr of guest.
    2) Check guest mac by qmp command.
    3) Set new mac in guest and regain new IP.
    4) Check guest new mac by qmp command.
    5) Re-log into guest with new MAC. (nettype != macvtap)
    6) Reboot guest and check the the mac address by monitor(optional).
    7) File transfer between host and guest. optional

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    # This session will be used to assess whether the IP change worked
    session = None
    if params.get("nettype") != "macvtap":
        session = vm.wait_for_login(timeout=timeout)
    old_mac = vm.get_mac_address(0)
    while True:
        vm.virtnet.free_mac_address(0)
        new_mac = vm.virtnet.generate_mac_address(0)
        if old_mac != new_mac:
            break

    os_type = params.get("os_type")
    os_variant = params.get("os_variant")
    change_cmd_pattern = params.get("change_cmd")
    test.log.info("The initial MAC address is %s", old_mac)
    check_guest_mac(test, old_mac, vm)
    if os_type == "linux":
        interface = utils_net.get_linux_ifname(session_serial, old_mac)
        if params.get("shutdown_int", "yes") == "yes":
            int_shutdown_cmd = params.get("int_shutdown_cmd", "ifconfig %s down")
            session_serial.cmd_output_safe(int_shutdown_cmd % interface)
    else:
        connection_id = utils_net.get_windows_nic_attribute(
            session_serial, "macaddress", old_mac, "netconnectionid"
        )
        nic_index = utils_net.get_windows_nic_attribute(
            session_serial, "netconnectionid", connection_id, "index"
        )
        if os_variant == "winxp" and session is not None:
            pnpdevice_id = utils_net.get_windows_nic_attribute(
                session, "netconnectionid", connection_id, "pnpdeviceid"
            )
            cd_drive = utils_misc.get_winutils_vol(session)
            copy_cmd = r"xcopy %s:\devcon\wxp_x86\devcon.exe c:\ " % cd_drive
            session.cmd(copy_cmd)

    # Start change MAC address
    error_context.context("Changing MAC address to %s" % new_mac, test.log.info)
    if os_type == "linux":
        change_cmd = change_cmd_pattern % (interface, new_mac)
    else:
        change_cmd = change_cmd_pattern % (int(nic_index), "".join(new_mac.split(":")))
    try:
        session_serial.cmd_output_safe(change_cmd)

        # Verify whether MAC address was changed to the new one
        error_context.context(
            "Verify the new mac address, and restart the network", test.log.info
        )
        if os_type == "linux":
            if params.get("shutdown_int", "yes") == "yes":
                int_activate_cmd = params.get("int_activate_cmd", "ifconfig %s up")
                session_serial.cmd_output_safe(int_activate_cmd % interface)
            session_serial.cmd_output_safe("ifconfig | grep -i %s" % new_mac)
            test.log.info("Mac address change successfully, net restart...")
            dhcp_cmd = params.get("dhcp_cmd")
            session_serial.sendline(dhcp_cmd % interface)
        else:
            mode = "netsh"
            if os_variant == "winxp":
                connection_id = pnpdevice_id.split("&")[-1]
                mode = "devcon"
            utils_net.restart_windows_guest_network(
                session_serial, connection_id, mode=mode
            )

            o = session_serial.cmd_output_safe("ipconfig /all")
            if params.get("ctrl_mac_addr") == "off":
                mac_check = old_mac
            else:
                mac_check = new_mac
            if not re.findall("%s" % "-".join(mac_check.split(":")), o, re.I):
                test.fail("Guest mac change failed")
            test.log.info("Guest mac have been modified successfully")

        if params.get("nettype") != "macvtap":
            # Re-log into the guest after changing mac address
            if utils_misc.wait_for(session.is_responsive, 120, 20, 3):
                # Just warning when failed to see the session become dead,
                # because there is a little chance the ip does not change.
                msg = "The session is still responsive, settings may fail."
                test.log.warning(msg)
            session.close()

            # In the following case, mac address should not change,
            # so set the old_mac back to virtnet cache
            # Or the vm will not able to be logined(no ip for the virtnet[0].mac)
            if os_type == "windows" and params.get("ctrl_mac_addr") == "off":
                nic = vm.virtnet[0]
                nic.mac = old_mac
                vm.virtnet.update_db()

            # Re-log into guest and check if session is responsive
            error_context.context("Re-log into the guest", test.log.info)
            session = vm.wait_for_login(timeout=timeout)
            if not session.is_responsive():
                test.error("The new session is not responsive.")
            if params.get("reboot_vm_after_mac_changed") == "yes":
                error_context.context(
                    "Reboot guest and check the the mac address by " "monitor",
                    test.log.info,
                )
                mac_check = new_mac
                if os_type == "linux":
                    nic = vm.virtnet[0]
                    nic.mac = old_mac
                    vm.virtnet.update_db()
                    mac_check = old_mac
                else:
                    if params.get("ctrl_mac_addr") == "off":
                        mac_check = old_mac

                session_serial = vm.reboot(session_serial, serial=True)
                check_guest_mac(test, mac_check, vm)
            if params.get("file_transfer", "no") == "yes":
                error_context.context(
                    "File transfer between host and guest.", test.log.info
                )
                utils_test.run_file_transfer(test, params, env)
        else:
            if params.get("ctrl_mac_addr") == "off":
                check_guest_mac(test, old_mac, vm)
            else:
                check_guest_mac(test, new_mac, vm)
    finally:
        if os_type == "windows":
            clean_cmd_pattern = params.get("clean_cmd")
            clean_cmd = clean_cmd_pattern % int(nic_index)
            session_serial.cmd_output_safe(clean_cmd)
            utils_net.restart_windows_guest_network(
                session_serial, connection_id, mode=mode
            )
            nic = vm.virtnet[0]
            nic.mac = old_mac
            vm.virtnet.update_db()
