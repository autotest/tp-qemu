import re

import aexpect
from virttest import error_context, test_setup, utils_misc, utils_net, utils_test

iface_scripts = []


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of sr-iov devices.

    (Elements between [] are configurable test parameters)
    1) Set up sr-iov test environment in host.
    2) Start VM.
    3) Disable the primary link(s) of guest.
    4) PCI add one/multi sr-io  deivce with (or without) repeat
    5) Compare output of monitor command 'info pci'.
    6) Compare output of guest command [reference_cmd].
    7) Verify whether pci_model is shown in [pci_find_cmd].
    8) Check whether the newly added PCI device works fine.
    9) Delete the device, verify whether could remove the sr-iov device.
    10) Re-enabling the primary link(s) of guest.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def check_interface(iface, nic_filter):
        cmd = "ifconfig %s" % str(iface)
        session = vm.wait_for_serial_login(timeout=timeout)
        status, output = session.cmd_status_output(cmd)
        if status:
            test.error("Guest command '%s' fail with output: %s." % (cmd, output))
        if re.findall(nic_filter, output, re.MULTILINE | re.DOTALL):
            return True
        return False

    def get_active_network_device(session, nic_filter):
        devnames = []
        cmd = "ifconfig -a"
        nic_reg = r"\w+(?=: flags)|\w+(?=\s*Link)"
        status, output = session.cmd_status_output(cmd)
        if status:
            test.error("Guest command '%s' fail with output: %s." % (cmd, output))
        ifaces = re.findall(nic_reg, output)
        for iface in ifaces:
            if check_interface(str(iface), nic_filter):
                devnames.append(iface)
        return devnames

    def pci_add_iov(pci_num):
        pci_add_cmd = "pci_add pci_addr=auto host host=%s,if=%s" % (
            pa_pci_ids[pci_num],
            pci_model,
        )
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return pci_add(pci_add_cmd)

    def pci_add(pci_add_cmd):
        error_context.context("Adding pci device with command 'pci_add'")
        add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info.append(["", add_output])
        if "OK domain" not in add_output:
            test.fail(
                "Add PCI device failed. Monitor command is: %s, "
                "Output: %r" % (pci_add_cmd, add_output)
            )
        return vm.monitor.info("pci")

    def check_support_device(dev):
        if vm.monitor.protocol == "qmp":
            devices_supported = vm.monitor.human_monitor_cmd("%s ?" % cmd_type)
        else:
            devices_supported = vm.monitor.send_args_cmd("%s ?" % cmd_type)
        # Check if the device is support in qemu
        is_support = utils_misc.find_substring(devices_supported, dev)
        if not is_support:
            test.error("%s doesn't support device: %s" % (cmd_type, dev))

    def device_add_iov(pci_num):
        device_id = "%s" % pci_model + "-" + utils_misc.generate_random_id()
        pci_info.append([device_id])
        driver = params.get("device_driver", "pci-assign")
        check_support_device(driver)
        pci_add_cmd = "device_add id=%s,driver=%s,host=%s" % (
            pci_info[pci_num][0],
            driver,
            pa_pci_ids[pci_num],
        )
        if params.get("hotplug_params"):
            assign_param = params.get("hotplug_params").split()
            for param in assign_param:
                value = params.get(param)
                if value:
                    pci_add_cmd += ",%s=%s" % (param, value)
        return device_add(pci_num, pci_add_cmd)

    def device_add(pci_num, pci_add_cmd):
        error_context.context("Adding pci device with command 'device_add'")
        if vm.monitor.protocol == "qmp":
            add_output = vm.monitor.send_args_cmd(pci_add_cmd)
        else:
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info[pci_num].append(add_output)
        after_add = vm.monitor.info("pci")
        if pci_info[pci_num][0] not in str(after_add):
            test.log.debug("Print info pci after add the block: %s", after_add)
            test.fail(
                "Add device failed. Monitor command is: %s"
                ". Output: %r" % (pci_add_cmd, add_output)
            )
        return after_add

    def clean_network_scripts():
        test.log.debug("Clean up network scripts in guest")
        session = vm.wait_for_serial_login(timeout=timeout)
        if "ubuntu" in vm.get_distro().lower():
            iface_script = "/etc/network/interfaces"
            cmd = "cat %s.BACKUP" % iface_script
            if not session.cmd_status(cmd):
                cmd = "mv %s.BACKUP %s" % (iface_script, iface_script)
                status, output = session.cmd_status_output(cmd)
                if status:
                    test.error(
                        "Failed to cleanup network script in guest: " "%s" % output
                    )
        else:
            global iface_scripts
            for iface_script in iface_scripts:
                cmd = "rm -f %s" % iface_script
                status, output = session.cmd_status_output(cmd)
                if status:
                    test.error("Failed to delete iface_script")
                iface_scripts.remove(iface_script)

    # Hot add a pci device
    def add_device(pci_num):
        global iface_scripts
        reference_cmd = params["reference_cmd"]
        info_pci_ref = vm.monitor.info("pci")
        session = vm.wait_for_serial_login(timeout=timeout)
        reference = session.cmd_output(reference_cmd)
        active_nics = get_active_network_device(session, nic_filter)
        test.log.debug("Active nics before hotplug - %s", active_nics)

        # Stop the VM monitor and try hot adding SRIOV dev
        if params.get("vm_stop", "no") == "yes":
            test.log.debug("stop the monitor of the VM before hotplug")
            vm.pause()
        try:
            # get function for adding device.
            add_function = local_functions["%s_iov" % cmd_type]
        except Exception:
            test.error("No function for adding sr-iov dev with '%s'" % cmd_type)
        after_add = None
        if add_function:
            # Do add pci device.
            after_add = add_function(pci_num)

        try:
            # Define a helper function to compare the output
            def _new_shown():
                output = session.cmd_output(reference_cmd)
                return output != reference

            # Define a helper function to make sure new nic could get ip.
            def _check_ip():
                post_nics = get_active_network_device(session, nic_filter)
                test.log.debug("Active nics after hotplug - %s", post_nics)
                return len(active_nics) <= len(post_nics) and active_nics != post_nics

            # Define a helper function to catch PCI device string
            def _find_pci():
                output = session.cmd_output("lspci -nn")
                if re.search(vf_filter, output, re.IGNORECASE):
                    return True
                else:
                    return False

            # Resume the VM
            if params.get("vm_resume", "no") == "yes":
                test.log.debug("resuming the VM after hotplug")
                vm.resume()

            # Reboot the VM
            if params.get("vm_reboot", "no") == "yes":
                test.log.debug("Rebooting the VM after hotplug")
                vm.reboot()
            session = vm.wait_for_serial_login(timeout=timeout)

            error_context.context("Start checking new added device")
            # Compare the output of 'info pci'
            if after_add == info_pci_ref:
                test.fail(
                    "No new PCI device shown after executing "
                    "monitor command: 'info pci'"
                )

            secs = int(params["wait_secs_for_hook_up"])
            if not utils_misc.wait_for(_new_shown, test_timeout, secs, 3):
                test.fail(
                    "No new device shown in output of command "
                    "executed inside the guest: %s" % reference_cmd
                )

            if not utils_misc.wait_for(_find_pci, test_timeout, 3, 3):
                test.fail(
                    "New add device not found in guest. " "Command was: lspci -nn"
                )

            # Assign static IP to the hotplugged interface
            if params.get("assign_static_ip", "no") == "yes":
                cmd = "service networking restart"
                static_ip = next(ip_gen)
                net_mask = params.get("static_net_mask", "255.255.255.0")
                params.get("static_broadcast", "10.10.10.255")
                pci_id = utils_misc.get_pci_id_using_filter(vf_filter, session)
                test.log.debug(
                    "PCIs associated with %s - %s",
                    vf_filter,
                    ", ".join(map(str, pci_id)),
                )
                for each_pci in pci_id:
                    iface_name = utils_misc.get_interface_from_pci_id(each_pci, session)
                    test.log.debug(
                        "Interface associated with PCI %s - %s", each_pci, iface_name
                    )
                    mac = session.cmd_output("ethtool -P %s" % iface_name)
                    mac = mac.split("Permanent address:")[-1].strip()
                    test.log.debug("mac address of %s: %s", iface_name, mac)
                    # backup the network script for other distros
                    if "ubuntu" not in vm.get_distro().lower():
                        cmd = "service network restart"
                        iface_scripts.append(utils_net.get_network_cfg_file(iface_name))
                    if not check_interface(str(iface_name), nic_filter):
                        utils_net.create_network_script(
                            iface_name,
                            mac,
                            boot_proto="static",
                            net_mask=net_mask,
                            vm=vm,
                            ip_addr=static_ip,
                        )
                        status, output = session.cmd_status_output(cmd)
                        if status:
                            test.error(
                                "Failed to set static ip in guest: " "%s" % output
                            )
            # Test the newly added device
            if not utils_misc.wait_for(_check_ip, 120, 3, 3):
                ifconfig = session.cmd_output("ifconfig -a")
                test.fail(
                    "New hotpluged device could not get ip "
                    "after 120s in guest. guest ifconfig "
                    "output: \n%s" % ifconfig
                )
            try:
                session.cmd(params["pci_test_cmd"] % (pci_num + 1))
            except aexpect.ShellError as e:
                test.fail(
                    "Check device failed after PCI " "hotplug. Output: %r" % e.output
                )

        except Exception:
            pci_del(pci_num, ignore_failure=True)
            raise

    # Hot delete a pci device
    def pci_del(pci_num, ignore_failure=False):
        def _device_removed():
            after_del = vm.monitor.info("pci")
            return after_del != before_del

        before_del = vm.monitor.info("pci")
        if cmd_type == "pci_add":
            slot_id = "0" + pci_info[pci_num][1].split(",")[2].split()[1]
            cmd = "pci_del pci_addr=%s" % slot_id
            vm.monitor.send_args_cmd(cmd, convert=False)
        elif cmd_type == "device_add":
            cmd = "device_del id=%s" % pci_info[pci_num][0]
            vm.monitor.send_args_cmd(cmd)

        if (
            not utils_misc.wait_for(_device_removed, test_timeout, 0, 1)
            and not ignore_failure
        ):
            test.fail(
                "Failed to hot remove PCI device: %s. "
                "Monitor command: %s" % (pci_model, cmd)
            )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_serial_login(timeout=timeout)

    test_timeout = int(params.get("test_timeout", 360))
    # Test if it is nic or block
    pci_num_range = int(params.get("pci_num", 1))
    rp_times = int(params.get("repeat_times", 1))
    pci_model = params.get("pci_model", "pci-assign")
    vf_filter = params.get("vf_filter_re")
    generate_mac = params.get("generate_mac", "yes")
    nic_filter = params["nic_interface_filter"]
    devices = []
    device_type = params.get("hotplug_device_type", "vf")
    for i in range(pci_num_range):
        device = {}
        device["type"] = device_type
        if generate_mac == "yes":
            device["mac"] = utils_net.generate_mac_address_simple()
        if params.get("device_name"):
            device["name"] = params.get("device_name")
        devices.append(device)
    device_driver = params.get("device_driver", "pci-assign")
    if vm.pci_assignable is None:
        vm.pci_assignable = test_setup.PciAssignable(
            driver=params.get("driver"),
            driver_option=params.get("driver_option"),
            host_set_flag=params.get("host_setup_flag"),
            kvm_params=params.get("kvm_default"),
            vf_filter_re=vf_filter,
            pf_filter_re=params.get("pf_filter_re"),
            device_driver=device_driver,
            pa_type=params.get("pci_assignable"),
        )

    pa_pci_ids = vm.pci_assignable.request_devs(devices)
    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        error_context.context("modprobe the module %s" % module, test.log.info)
        session.cmd("modprobe %s" % module)

    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == "qmp":
        cmd_o = vm.monitor.info("commands")
    else:
        cmd_o = vm.monitor.send_args_cmd("help")

    cmd_type = utils_misc.find_substring(str(cmd_o), "device_add", "pci_add")
    if not cmd_o:
        test.error("Unknown version of qemu")

    local_functions = locals()

    if params.get("enable_set_link" "yes") == "yes":
        error_context.context("Disable the primary link(s) of guest", test.log.info)
        for nic in vm.virtnet:
            vm.set_link(nic.device_id, up=False)

    try:
        for j in range(rp_times):
            # pci_info is a list of list.
            # each element 'i' has 4 members:
            # pci_info[i][0] == device id, only used for device_add
            # pci_info[i][1] == output of device add command
            pci_info = []
            if params.get("assign_static_ip", "no") == "yes":
                ip_gen = utils_net.gen_ipv4_addr(exclude_ips=[])
                # backup the network script file if it is ubuntu
                if "ubuntu" in vm.get_distro().lower():
                    session = vm.wait_for_serial_login(timeout=timeout)
                    iface_script = "/etc/network/interfaces"
                    cmd = "cat %s" % iface_script
                    if not session.cmd_status(cmd):
                        test.log.debug(
                            "Backup network script in guest - %s", iface_script
                        )
                        cmd = "cp %s %s.BACKUP" % (iface_script, iface_script)
                        status, output = session.cmd_status_output(cmd)
                        if status:
                            test.error("Failed to backup in guest: %s" % output)
            for pci_num in range(pci_num_range):
                msg = "Start hot-adding %sth pci device," % (pci_num + 1)
                msg += " repeat %d" % (j + 1)
                error_context.context(msg, test.log.info)
                add_device(pci_num)
            sub_type = params.get("sub_type_after_plug")
            if sub_type:
                error_context.context(
                    "Running sub test '%s' after hotplug" % sub_type, test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_type)
                if "guest_suspend" == sub_type:
                    # Hotpluged device have been released after guest suspend,
                    # so do not need unpluged step.
                    break
            for pci_num in range(pci_num_range):
                msg = "start hot-deleting %sth pci device," % (pci_num + 1)
                msg += " repeat %d" % (j + 1)
                error_context.context(msg, test.log.info)
                pci_del(-(pci_num + 1))

            # cleanup network script after hot deleting pci device
            clean_network_scripts()
    finally:
        # clean network scripts on error
        clean_network_scripts()
        if params.get("enable_set_link", "yes") == "yes":
            error_context.context(
                "Re-enabling the primary link(s) of guest", test.log.info
            )
            for nic in vm.virtnet:
                vm.set_link(nic.device_id, up=True)
        if session:
            session.close()
