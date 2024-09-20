import time

import aexpect
from virttest import error_context, remote, utils_misc, utils_net, utils_test, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    KVM guest link test:
    1) Boot up guest with one nic
    2) Disable guest link by set_link
    3) Check guest nic operstate and ping host from guest,
       will change queues number at the same time, when using mq
    4) Reboot the guest, then check guest nic operstate and do ping test
    5) Re-enable guest link by set_link
    6) Check guest nic operstate and ping host from guest,
       will change queues number at the same time, when using mq
    7) Reboot the guest, then check guest nic operstate and do ping test
    8) Call utils_test.run_file_transfer function to test file transfer.
       It will do following steps:
       8.1) Create a large file by dd on host.
       8.2) Copy this file from host to guest.
       8.3) Copy this file from guest to host.
       8.4) Check if file transfers ended good.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def change_queues_number(session, ifname, q_number):
        """
        Change queues number, only used for mq test
        """
        mq_set_cmd = "ethtool -L %s combined %s" % (ifname, q_number)
        try:
            session.cmd_output_safe(mq_set_cmd)
        except aexpect.ShellError as err:
            err_msg = "Change queues number failed"
            err_msg += "Error info: '%s'" % err
            test.fail(err_msg)

    def change_queues_number_repeatly(guest_ifname):
        """
        Change queues repeatedly, only for mq test
        """
        session = vm.wait_for_serial_login()
        try:
            queues = params.get("queues", 1)
            change_list = range(1, int(queues) + 1)
            env["run_change_queues"] = True
            change_queues_number(session, guest_ifname, queues)
            while env["run_change_queues"]:
                for q_number in change_list:
                    change_queues_number(session, guest_ifname, q_number)
        finally:
            if "run_change_queues" in env:
                del env["run_change_queues"]
            session.close()

    def guest_reboot(reboot_method, link_up):
        """
        Reboot guest by different method (shell/system_reset)
        """
        try:
            vm.reboot(method=reboot_method, serial=True, timeout=120)
        except (remote.LoginError, virt_vm.VMAddressError):
            if not link_up:
                test.log.info("Login error is expected when net link is down")

    def guest_netwok_connecting_check(guest_ip, link_up, change_queues=False):
        """
        Check whether guest network is connective by ping
        """
        if change_queues:
            env["run_change_queues"] = False
            bg_thread = utils_misc.InterruptedThread(
                change_queues_number_repeatly, (guest_ifname,)
            )
            bg_thread.start()

            utils_misc.wait_for(
                lambda: env["run_change_queues"], 30, 0, 2, "wait queues change start"
            )
        time.sleep(0.5)
        output = utils_test.ping(
            guest_ip, 10, interface=host_interface, timeout=20, session=None
        )[1]
        if not link_up and utils_test.get_loss_ratio(output) < 80:
            err_msg = "guest network still connecting after down the link"
            test.fail(err_msg)
        elif link_up and utils_test.get_loss_ratio(output) > 20:
            err_msg = "All packets lost during ping guest ip after link up"
            test.fail(err_msg)

        if change_queues:
            env["run_change_queues"] = False
            bg_thread.join()

    def operstate_check(session, expect_status, guest_ifname=""):
        """
        Check Guest interface operstate
        """
        if params.get("os_type") == "linux":
            if_operstate = utils_net.get_net_if_operstate(
                guest_ifname, session.cmd_output_safe
            )
        else:
            if_operstate = utils_net.get_windows_nic_attribute(
                session, "macaddress", vm.get_mac_address(), "netconnectionstatus"
            )

        if if_operstate != expect_status:
            err_msg = "Guest interface %s status error, " % guest_ifname
            err_msg = "currently interface status is '%s', " % if_operstate
            err_msg += "but expect status is '%s'" % expect_status
            test.fail(err_msg)
        test.log.info(
            "Guest interface operstate '%s' is exactly as expected", if_operstate
        )

    def guest_interface_operstate_check(
        expect_status, guest_ifname="", change_queues=False
    ):
        """
        Check guest interface operstate, support mq
        """
        session = vm.wait_for_serial_login()
        try:
            if change_queues:
                queues = params.get("queues", 1)
                change_list = range(1, int(queues) + 1)
                for q_number in change_list:
                    change_queues_number(session, guest_ifname, q_number)
                    operstate_check(session, expect_status, guest_ifname)
            else:
                operstate_check(session, expect_status, guest_ifname)
        finally:
            session.close()

    def check_interface_ip_routine(session, mac_addr):
        """
        The routine to check the ip of interface.

        :param session: a session to send check commands
        :param mac_addr: the interface mac address
        """
        ip_addr = utils_net.get_net_if_addrs_win(session, mac_addr)
        guest_ipv4 = ip_addr["ipv4"]
        for ip in guest_ipv4:
            test.log.debug("Check address: %s", ip)
            if len(ip) != 0 and not ip.startswith("169.254"):
                return True
        return False

    def check_interface_ip(timeout=600):
        """
        Check whether the vm has got the available ip address.

        The check will be performed repeatedly until a correct ip address
        is detected or after the specified time is expired.

        :param timeout: total checking time allowed
        """
        error_context.context("Start checking guest ip", test.log.info)
        session = vm.wait_for_serial_login()
        mac_addr = vm.get_mac_address()
        try:
            if not utils_misc.wait_for(
                lambda: check_interface_ip_routine(session, mac_addr), timeout, step=5.0
            ):
                err_msg = "Can't get valid ip in %s seconds" % timeout
                test.fail(err_msg)
        finally:
            session.close()

    def set_link_test(
        linkid, link_up, expect_status, change_queues=False, operstate_always_up=False
    ):
        """
        Issue set_link commands and test its function

        :param linkid: id of netdev or devices to be tested
        :param link_up: flag linkid is up or down
        :param expect_status : expect guest operstate status"
        :param operstate_always_up: when linkid is netdev id, guest interface
                                    operstate will never change,
                                    need set it to True.
        :param change_queues: whether run change mq queues, only effect on
                              linux guest with mq nic.

        """
        vm.set_link(linkid, up=link_up)
        time.sleep(1)
        error_context.context("Check guest interface operstate", test.log.info)
        if operstate_always_up:
            if expect_status == "down":
                expect_status = "up"
            if expect_status == win_media_disconnected:
                expect_status = win_media_connected
        guest_interface_operstate_check(expect_status, guest_ifname, change_queues)
        if params.get("os_type") == "windows" and expect_status == win_media_connected:
            check_interface_ip()

        error_context.context("Check if guest network connective", test.log.info)
        guest_netwok_connecting_check(guest_ip, link_up, change_queues)

        reboot_method = params.get("reboot_method", "shell")

        error_context.context(
            "Reboot guest by '%s' and recheck interface " "operstate" % reboot_method,
            test.log.info,
        )
        guest_reboot(reboot_method, link_up)
        guest_interface_operstate_check(expect_status, guest_ifname, change_queues)

        error_context.context(
            "Check guest network connecting after reboot " "by '%s'" % reboot_method,
            test.log.info,
        )
        guest_netwok_connecting_check(guest_ip, link_up, change_queues)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    netdev_id = vm.virtnet[0].netdev_id
    device_id = vm.virtnet[0].device_id
    device_mac = vm.virtnet[0].mac
    host_interface = None
    if vm.virtnet[0].netdst:
        host_interface = vm.virtnet[0].netdst
    os_type = params.get("os_type", "linux")
    login_timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    change_queues = False
    guest_ifname = ""
    guest_ip = utils_net.get_guest_ip_addr(session, device_mac, os_type)
    # Win guest '2' represent 'Connected', '7' represent 'Media disconnected'
    win_media_connected = params.get("win_media_connected", "2")
    win_media_disconnected = params.get("win_media_disconnected", "7")

    if os_type == "linux":
        guest_ifname = utils_net.get_linux_ifname(session, vm.get_mac_address())
        queues = int(params.get("queues", 1))
        if queues != 1 and vm.virtnet[0].nic_model == "virtio":
            change_queues = True

    session.close()

    expect_down_status = params.get("down-status", "down")
    expect_up_status = params.get("up-status", "up")
    operstate_always_up = params.get("operstate_always_up", "no") == "yes"

    error_context.context(
        "Disable guest netdev link '%s' by set_link" % netdev_id, test.log.info
    )
    set_link_test(
        netdev_id, False, expect_down_status, change_queues, operstate_always_up
    )

    error_context.context(
        "Re-enable guest netdev link '%s' by set_link" % netdev_id, test.log.info
    )
    set_link_test(netdev_id, True, expect_up_status, change_queues, operstate_always_up)

    error_context.context(
        "Disable guest nic device '%s' by set_link" % device_id, test.log.info
    )
    set_link_test(device_id, False, expect_down_status, change_queues)

    error_context.context(
        "Re-enable guest nic device '%s' by set_link" % device_id, test.log.info
    )
    set_link_test(device_id, True, expect_up_status, change_queues)

    error_context.context("Do file transfer after setlink on and off", test.log.info)
    utils_test.run_file_transfer(test, params, env)
