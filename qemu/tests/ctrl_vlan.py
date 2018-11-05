import logging

from virttest import error_context
from virttest import utils_net
from virttest import utils_test


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
        error_context.context("Check vlan table in rx-filter", logging.info)
        query_cmd = "query-rx-filter name=%s" % vm.virtnet[0].device_id
        vlan_table = vm.monitor.send_args_cmd(query_cmd)[0].get("vlan-table")
        if not expect_vlan:
            vlan_table.sort()
            if (len(set(vlan_table)) == 4096 and vlan_table[0] == 0 and
                    vlan_table[-1] == 4095):
                pass
            else:
                test.fail("Guest vlan table is not correct, expect: %s,"
                          " actual: %s"
                          % (expect_vlan, vlan_table))
        elif vlan_table and vlan_table[0] != int(expect_vlan):
            test.fail("Guest vlan table is not correct, expect: %s, actual: %s"
                      % (expect_vlan, vlan_table[0]))

    login_timeout = float(params.get("login_timeout", 360))
    error_context.context("Init the VM, and try to login", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)

    if ("ctrl_vlan=on" in params["nic_extra_params"] and
            params["os_type"] == "linux"):
        expect_vlan = vm.virtnet[0].vlan
    else:
        expect_vlan = None

    if params["os_type"] == "windows":
        error_context.context("Verify if netkvm.sys is enabled in guest",
                              logging.info)
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, "netkvm",
                                                                timeout=120)
    verify_vlan_table(expect_vlan)

    if "ctrl_vlan=on" in params["nic_extra_params"]:
        error_context.context("Add vlan tag for guest network", logging.info)
        vlan_set_cmd = params["vlan_set_cmd"]
        vlan_id = params["vlan_id"]
        if params["os_type"] == "linux":
            ifname = utils_net.get_linux_ifname(session, vm.virtnet[0].mac)
            vlan_set_cmd = vlan_set_cmd % (ifname, ifname, ifname, ifname)
        else:
            ifname = utils_net.get_windows_nic_attribute(session=session,
                                                         key="netenabled",
                                                         value=True,
                                                         target="netconnectionID")
            vlan_set_cmd = vlan_set_cmd % ifname
        status, output = session.cmd_status_output(vlan_set_cmd)
        if status:
            test.error("Error occured when set vlan tag for network interface: %s, "
                       "err info: %s " % (ifname, output))
        verify_vlan_table(vlan_id)
