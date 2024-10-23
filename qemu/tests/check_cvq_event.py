from virttest import error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Check if QEMU is able to check CVQ by issuing NIC_RX_FILTER_CHANGED event

    1) Boot a guest with vdpa device
    2) Connected to QMP via telnet and consumed the rx-filter of the nic
    3) Changed the MAC address of the nic in the guest
    4) Qemu emit an event via QMP right after that, what signals that QEMU is
       intercepting CVQ with SVQ
    5) Changed the MAC address again, Qemu was not sending more
       NIC_RX_FILTER_CHANGED events

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    old_mac = vm.get_mac_address(0)
    new_mac = vm.virtnet.generate_mac_address(0)
    interface = utils_net.get_linux_ifname(session_serial, old_mac)
    change_cmd = params.get("change_cmd")
    guest_nic = vm.virtnet
    device_id = guest_nic[0].device_id
    test.log.info("Consumed the rx-filter of the nic")
    vm.monitor.cmd("query-rx-filter", args={"name": device_id})
    test.log.info("Changed the mac address inside guest")
    session_serial.cmd_output_safe(change_cmd % (new_mac, interface))
    test.log.info("Check qemu if sent a NIC_RX_FILTER_CHANGED event")
    event_name = params.get("event_name")
    if vm.monitor.get_event(event_name):
        test.log.info("Received qmp %s event notification", event_name)
    else:
        test.fail("Can not got %s event notification" % event_name)
    vm.monitor.clear_event(event_name)
    test.log.info("Changed the mac address again inside guest")
    session_serial.cmd_output_safe(change_cmd % (old_mac, interface))
    if vm.monitor.get_event(event_name):
        test.fail("Oops, Received qmp %s event notification again" % event_name)
    else:
        test.log.info("Test pass, there is no any event notification")
    session_serial.close()
