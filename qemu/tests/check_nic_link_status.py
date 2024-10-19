import time

from virttest import error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    KVM guest link test:
    1) Boot up guest with one nic
    2) Disable guest link by set_link before guest os boot up
    3) Check guest nic operstate status
    4) Reboot the guest, then check guest nic operstate
    5) Re-enable guest link by set_link
    6) Check guest nic operstate and ping host from guest

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def guest_interface_operstate_check(session, expect_status):
        """
        Check Guest interface operstate
        """
        if params.get("os_type") == "linux":
            guest_ifname = utils_net.get_linux_ifname(session, vm.get_mac_address())
            if_operstate = utils_net.get_net_if_operstate(
                guest_ifname, session.cmd_output_safe
            )
        else:
            if_operstate = utils_net.get_windows_nic_attribute(
                session, "macaddress", vm.get_mac_address(), "netconnectionstatus"
            )

        if if_operstate != expect_status:
            err_msg = "Guest interface %s status error, " % guest_ifname
            err_msg += "currently interface status is '%s', " % if_operstate
            err_msg += "but expect status is '%s'" % expect_status
            test.fail(err_msg)
        test.log.info(
            "Guest interface operstate '%s' is exactly as expected", if_operstate
        )

    def set_link_test(linkid, link_up):
        """
        Issue set_link commands and test its function

        :param linkid: id of devices to be tested
        :param link_up: flag linkid is up or down

        """
        vm.set_link(linkid, up=link_up)
        time.sleep(1)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    device_id = vm.virtnet[0].device_id
    device_mac = vm.virtnet[0].mac
    set_link_test(device_id, False)
    vm.resume()
    login_timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_serial_login(timeout=login_timeout)
    # Win guest '2' represent 'Connected', '7' represent 'Media disconnected'
    os_type = params.get("os_type")
    expect_down_status = params.get("down-status", "down")
    expect_up_status = params.get("up-status", "up")

    reboot_method = params.get("reboot_method", "shell")

    error_context.context("Check guest interface operstate", test.log.info)
    guest_interface_operstate_check(session, expect_down_status)

    error_context.context(
        "Reboot guest by '%s' and recheck interface " "operstate" % reboot_method,
        test.log.info,
    )
    session = vm.reboot(method=reboot_method, serial=True, timeout=360, session=session)
    guest_interface_operstate_check(session, expect_down_status)

    error_context.context(
        "Re-enable guest nic device '%s' by set_link" % device_id, test.log.info
    )
    set_link_test(device_id, True)
    guest_interface_operstate_check(session, expect_up_status)

    error_context.context(
        "Check guest network connecting by set_link to '%s'" % expect_up_status,
        test.log.info,
    )
    # Windows guest need about 60s to get the ip address
    guest_ip = utils_net.get_guest_ip_addr(session, device_mac, os_type, timeout=60)
    if guest_ip is None:
        utils_net.restart_guest_network(session, device_mac, os_type)
    status, output = utils_test.ping(guest_ip, 10, timeout=30, session=session)
    if status:
        test.fail("%s ping host unexpected, output %s" % (vm.name, output))
    session.close()
