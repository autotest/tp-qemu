import time

from virttest import error_context, utils_net, utils_test, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration. If it does, proceed with
       the test.
    3) Hotplug(Hotunplug) a nic.
    4) Disable the primary link of guest(optional).
    5) Check if new interface gets ip address(optional).
    6) Ping guest's new ip from host(optional).
    7) Re-enabling the primary link(optional).
    8) Send a migration command to the source VM and wait until it's finished.
    9) Disable the primary link again(optional).
    10) Ping guest's new ip from host(optional).
    11) Re-enabling the primary link(optiona).

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def set_link(nic_name, up=False):
        for nic in vm.virtnet:
            if nic.nic_name != nic_name:
                vm.set_link(nic.device_id, up=up)

    def check_nic_is_empty():
        """
        Check whether the nic status in guest is empty after unplug.
        """

        session_serial = vm.wait_for_serial_login(timeout=timeout)
        status, output = session_serial.cmd_status_output(check_nic_cmd)
        session_serial.close()

        if guest_is_not_windows:
            # grep return code: match(0), un-match(1), error(2)
            if status != 1:
                test.fail("nic is not empty with output: %s" % output)
        else:
            if status:
                test.error(
                    "Error occured when get nic status, "
                    "with status=%s, output=%s" % (status, output)
                )
            if "Ethernet" in output:
                test.fail("nic is not empty with output: %s" % output)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)

    guest_is_not_windows = params.get("os_type") != "windows"
    run_dhclient = params.get("run_dhclient", "no")
    mig_timeout = float(params.get("mig_timeout", "3600"))
    nettype = params.get("nettype", "bridge")
    netdst = params.get("netdst", "virbr0")
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    pci_model = params.get("pci_model")
    with_unplug = params.get("with_unplug", "no") == "yes"
    check_nic_cmd = params.get("check_nic_cmd")

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if guest_is_not_windows and module:
        session_serial.cmd("modprobe %s" % module)
    if session_serial:
        session_serial.close()

    if with_unplug:
        nic_name = vm.virtnet[0].nic_name
        error_context.context(
            "Hot unplug %s before migration" % nic_name, test.log.info
        )
        vm.hotunplug_nic(nic_name)
        error_context.context("Check whether the guest's nic is empty", test.log.info)
        check_nic_is_empty()
        vm.params["nics"] = ""
        if "q35" in params["machine_type"]:
            vm.params["pcie_extra_root_port"] = 1
    else:
        error_context.context("Add network devices through monitor cmd", test.log.info)
        nic_name = "hotadded"
        enable_msix_vectors = params.get("enable_msix_vectors")
        nic_info = vm.hotplug_nic(
            nic_model=pci_model,
            nic_name=nic_name,
            netdst=netdst,
            nettype=nettype,
            queues=params.get("queues"),
            enable_msix_vectors=enable_msix_vectors,
        )
        nic_mac = nic_info["mac"]
        vm.params["nics"] += " %s" % nic_name
        vm.params["nic_model_%s" % nic_name] = nic_info["nic_model"]

        # Only run dhclient if explicitly set and guest is not running Windows.
        # Most modern Linux guests run NetworkManager, and thus do not need this.
        if run_dhclient == "yes" and guest_is_not_windows:
            session_serial = vm.wait_for_serial_login(timeout=timeout)
            ifname = utils_net.get_linux_ifname(session_serial, nic_mac)
            utils_net.restart_guest_network(session_serial, ifname)
            # Guest need to take quite a long time to set the ip addr, sleep a
            # while to wait for guest done.
            time.sleep(60)

        error_context.context("Disable the primary link of guest", test.log.info)
        set_link(nic_name, up=False)

        error_context.context("Check if new interface gets ip address", test.log.info)
        try:
            ip = vm.wait_for_get_address(nic_name)
        except virt_vm.VMIPAddressMissingError:
            test.fail("Could not get or verify ip address of nic")
        test.log.info("Got the ip address of new nic: %s", ip)

        error_context.context("Ping guest's new ip from host", test.log.info)
        s, o = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            test.fail("New nic failed ping test with output:\n %s" % o)

        error_context.context("Re-enabling the primary link", test.log.info)
        set_link(nic_name, up=True)

    error_context.context("Migrate from source VM to Destination VM", test.log.info)
    vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay, env=env)

    if with_unplug:
        error_context.context(
            "Check whether the guest's nic is still empty after migration",
            test.log.info,
        )
        check_nic_is_empty()
    else:
        error_context.context("Disable the primary link", test.log.info)
        set_link(nic_name, up=False)

        error_context.context("Ping guest's new ip from host", test.log.info)
        s, o = utils_test.ping(ip, 10, timeout=15)
        if s != 0:
            test.fail("New nic failed ping test with output:\n %s" % o)

        error_context.context("Re-enabling the primary link", test.log.info)
        set_link(nic_name, up=True)

        error_context.context("Reboot guest and verify new nic works", test.log.info)
        host_ip = utils_net.get_ip_address_by_interface(netdst)
        session = vm.reboot()
        status, output = utils_test.ping(
            dest=host_ip, count=100, timeout=240, session=session
        )
        if status != 0:
            test.fail("Fail to ping host form guest")
