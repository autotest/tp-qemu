import time

from virttest import error_context, utils_net, utils_test
from virttest.utils_windows import virtio_win


@error_context.context_aware
def run(test, params, env):
    """
    Run ctrl_vlan check test.

    1) Boot vm with ctrl_vlan=on/off
    2) Verify if netkvm.sys is enabled in guest(only windows)
    3) Check vlan table in rx-filter information
    4) If ctrl_vlan=on, do step 5-6
    5) Set vlan in guest
    6) Check vlan table in rx-filter information again

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def verify_vlan_table(expect_vlan=None):
        error_context.context("Check vlan table in rx-filter", test.log.info)
        query_cmd = "query-rx-filter name=%s" % vm.virtnet[0].device_id
        vlan_table = vm.monitor.send_args_cmd(query_cmd)[0].get("vlan-table")
        if not expect_vlan:
            vlan_table.sort()
            if (
                len(set(vlan_table)) == 4095
                and vlan_table[0] == 0
                and vlan_table[-1] == 4094
            ):
                pass
            else:
                test.fail(
                    "Guest vlan table is not correct, expect: %s,"
                    " actual: %s" % (expect_vlan, vlan_table)
                )
        elif vlan_table and vlan_table[0] != int(expect_vlan):
            test.fail(
                "Guest vlan table is not correct, expect: %s, actual: %s"
                % (expect_vlan, vlan_table[0])
            )

    def get_netkvmco_path(session):
        """
        Get the proper netkvmco.dll path from iso.

        :param session: a session to send cmd
        :return: the proper netkvmco.dll path
        """

        viowin_ltr = virtio_win.drive_letter_iso(session)
        if not viowin_ltr:
            err = "Could not find virtio-win drive in guest"
            test.error(err)
        guest_name = virtio_win.product_dirname_iso(session)
        if not guest_name:
            err = "Could not get product dirname of the vm"
            test.error(err)
        guest_arch = virtio_win.arch_dirname_iso(session)
        if not guest_arch:
            err = "Could not get architecture dirname of the vm"
            test.error(err)

        middle_path = "%s\\%s" % (guest_name, guest_arch)
        find_cmd = 'dir /b /s %s\\netkvmco.dll | findstr "\\%s\\\\"'
        find_cmd %= (viowin_ltr, middle_path)
        netkvmco_path = session.cmd(find_cmd).strip()
        test.log.info("Found netkvmco.dll file at %s", netkvmco_path)
        return netkvmco_path

    login_timeout = float(params.get("login_timeout", 360))
    error_context.context("Init the VM, and try to login", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    if "ctrl_vlan=on" in params["nic_extra_params"] and params["os_type"] == "linux":
        expect_vlan = vm.virtnet[0].vlan
    else:
        expect_vlan = None

    if "ctrl_vlan=on" in params["nic_extra_params"]:
        error_context.context("Add vlan tag for guest network", test.log.info)
        vlan_set_cmd = params["vlan_set_cmd"]
        vlan_id = params["vlan_id"]
        try:
            if params["os_type"] == "linux":
                session = vm.wait_for_serial_login(timeout=login_timeout)
                verify_vlan_table(expect_vlan)
                ifname = utils_net.get_linux_ifname(session, vm.virtnet[0].mac)
                vlan_set_cmd = vlan_set_cmd % (ifname, ifname, ifname, ifname)
                status, output = session.cmd_status_output(vlan_set_cmd, safe=True)
                if status:
                    test.error(
                        "Error occured when set vlan tag for network interface: %s, "
                        "err info: %s " % (ifname, output)
                    )
            else:
                driver_verifier = params["driver_verifier"]
                session = vm.wait_for_login(timeout=login_timeout)
                error_context.context(
                    "Verify if netkvm.sys is enabled in guest", test.log.info
                )
                session = utils_test.qemu.windrv_check_running_verifier(
                    session, vm, test, driver_verifier, timeout=120
                )
                verify_vlan_table(expect_vlan)
                ifname = utils_net.get_windows_nic_attribute(
                    session=session,
                    key="netenabled",
                    value=True,
                    target="netconnectionID",
                )
                session = vm.wait_for_serial_login(timeout=login_timeout)
                status, output = session.cmd_status_output(vlan_set_cmd % ifname)
                if status:
                    test.error(
                        "Error occured when set vlan tag for "
                        "network interface: %s, err info: %s " % (ifname, output)
                    )
                # restart nic for windows guest
                dev_mac = vm.virtnet[0].mac
                connection_id = utils_net.get_windows_nic_attribute(
                    session, "macaddress", dev_mac, "netconnectionid"
                )
                utils_net.restart_windows_guest_network(session, connection_id)
                time.sleep(10)
        finally:
            if session:
                session.close()
        verify_vlan_table(vlan_id)
