import re

from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    KVM Seabios test:
    1) Start guest with sga bios
    2) Check the sga bios messages(optional)
    3) Hotplug a virtio-blk-pci device and a virtio-net-pci device
    4) Restart the guest
    5) Check whether the hotplugged devices are in the boot menu
    6) Hotunplug the hotplugged virtio-blk-pci and virtio-net-pci devices
    7) Restart the guest
    8) Check whether the hotunplugged devices are still in the boot menu

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_output(session_obj):
        """
        Use the function to short the lines in the scripts
        """
        if params["enable_sga"] == "yes":
            output = session_obj.get_stripped_output()
        else:
            output = session_obj.get_output()
        return output

    def sga_info_check():
        return re.search(sgabios_info, get_output(vm.serial_console))

    def menu_hint_check():
        return (
            len(re.findall(boot_menu_hint, get_output(seabios_session))) > reboot_times
        )

    def get_list():
        return re.findall(r"^\d+\. .*\s", get_output(seabios_session), re.M)

    def get_boot_menu():
        if not utils_misc.wait_for(menu_hint_check, timeout, 1):
            test.fail("Could not get boot menu message")
        vm.send_key(boot_menu_key)
        boot_list = utils_misc.wait_for(get_list, timeout, 1)
        boot_menu = boot_list[len(boot_list_record) :]
        if not boot_menu:
            test.fail("Could not get boot menu list")
        return (boot_list, boot_menu)

    def check_in_guest():
        session = vm.wait_for_serial_login(timeout=timeout, restart_network=True)
        error_context.context("Check kernel crash message!", test.log.info)
        vm.verify_kernel_crash()
        error_context.context("Ping guest!", test.log.info)
        guest_ip = vm.get_address()
        status, output = utils_test.ping(guest_ip, count=10, timeout=20)
        if status:
            test.fail("Ping guest failed!")
        elif utils_test.get_loss_ratio(output) == 100:
            test.fail("All packets lost during ping guest %s." % guest_ip)
        session.close()

    def get_diff(menu_before, menu_after, plug=False):
        if plug:
            (menu_short, menu_long) = (menu_before, menu_after)
        else:
            (menu_short, menu_long) = (menu_after, menu_before)
        menu_short = re.findall(r"^\d+\. (.*)\s", "".join(menu_short), re.M)
        menu_long = re.findall(r"^\d+\. (.*)\s", "".join(menu_long), re.M)
        for dev in menu_short:
            if dev in menu_long:
                menu_long.remove(dev)
        return menu_long

    error_context.context("Start guest with sga bios", test.log.info)
    timeout = float(params.get("login_timeout", 240))
    boot_menu_key = params["boot_menu_key"]
    boot_menu_hint = params["boot_menu_hint"]
    sgabios_info = params.get("sgabios_info")
    boot_device = int(params["bootindex_image1"]) + 1
    reboot_times = 0

    vm = env.get_vm(params["main_vm"])
    seabios_session = vm.logsessions["seabios"]

    if sgabios_info:
        error_context.context("Check the SGABIOS info", test.log.info)
        if not utils_misc.wait_for(sga_info_check, timeout, 1):
            err_msg = "Cound not get sgabios message. Output: %s"
            test.fail(err_msg % get_output(vm.serial_console))

    error_context.context("Check boot menu before hotplug", test.log.info)
    boot_list_record = []
    boot_list_record, boot_menu_before_plug = get_boot_menu()
    test.log.info("Got boot menu before hotplug: '%s'", boot_menu_before_plug)
    vm.send_key(str(boot_device))

    error_context.context("Hotplugging virtio disk", test.log.info)
    disk_hotplugged = []
    image_name = params.objects("images")[-1]
    image_params = params.object_params(image_name)
    image_params["drive_format"] = "virtio"
    image_hint = "Virtio disk"
    devices = vm.devices.images_define_by_params(
        image_name, image_params, "disk", None, False, None
    )
    for dev in devices:
        ret = vm.devices.simple_hotplug(dev, vm.monitor)
        if ret[1] is False:
            test.fail("Failed to hotplug device '%s'. Output:\n%s" % (dev, ret[0]))
    disk_hotplugged.append(devices[-1])

    error_context.context("Hotplugging virtio nic", test.log.info)
    nic_name = "hotplug_nic"
    nic_params = params.object_params(nic_name)
    nic_model = "virtio-net-pci"
    nic_params["nic_model"] = nic_model
    nic_params["nic_name"] = nic_name
    nic_params["device_id"] = nic_name
    nic_hint = "iPXE"

    test.log.info("Disable other link(s) in guest")
    guest_is_linux = "linux" == params.get("os_type")
    s_session = vm.wait_for_serial_login(timeout=timeout)
    primary_nics = [nic for nic in vm.virtnet]
    for nic in primary_nics:
        if guest_is_linux:
            ifname = utils_net.get_linux_ifname(s_session, nic["mac"])
            s_session.cmd_output_safe("ifconfig %s 0.0.0.0" % ifname)
        else:
            s_session.cmd_output_safe("ipconfig /release all")
        vm.set_link(nic.device_id, up=False)
    s_session.close()

    test.log.info("Hotplug '%s' nic named '%s'", nic_model, nic_name)
    hotplug_nic = vm.hotplug_nic(**nic_params)

    check_in_guest()

    error_context.context("Restart guest after hotplug", test.log.info)
    vm.system_reset()
    reboot_times += 1

    error_context.context("Check boot menu after hotplug", test.log.info)
    boot_list_record, boot_menu_after_plug = get_boot_menu()
    test.log.info("Got boot menu after hotplug: '%s'", boot_menu_after_plug)
    if not len(boot_menu_after_plug) > len(boot_menu_before_plug):
        test.fail("The boot menu is incorrect after hotplug.")
    menu_diff = get_diff(boot_menu_before_plug, boot_menu_after_plug, plug=True)
    if image_hint not in str(menu_diff):
        test.fail("Hotplugged virtio disk is not in boot menu list")
    if nic_hint not in str(menu_diff):
        test.fail("Hotplugged virtio nic is not in boot menu list")

    vm.send_key(str(boot_device))
    check_in_guest()

    error_context.context("Hotunplugging", test.log.info)
    for dev in disk_hotplugged:
        ret = vm.devices.simple_unplug(dev, vm.monitor)
        if ret[1] is False:
            test.fail("Failed to unplug device '%s'. Output:\n%s" % (dev, ret[0]))

    vm.hotunplug_nic(hotplug_nic.nic_name)
    for nic in primary_nics:
        vm.set_link(nic.device_id, up=True)

    error_context.context("Restart guest after hotunplug", test.log.info)
    vm.system_reset()
    reboot_times += 1

    error_context.context("Check boot menu after hotunplug", test.log.info)
    boot_list_record, boot_menu_after_unplug = get_boot_menu()
    test.log.info("Got boot menu after hotunplug: '%s'", boot_menu_after_unplug)
    if not len(boot_menu_after_plug) > len(boot_menu_after_unplug):
        test.fail("The boot menu is incorrect after hotunplug.")
    menu_diff = get_diff(boot_menu_after_plug, boot_menu_after_unplug, plug=False)
    if image_hint not in str(menu_diff):
        test.fail("Hotunplugged virtio disk is still in boot menu list")
    if nic_hint not in str(menu_diff):
        test.fail("Hotunplugged virtio nic is still in boot menu list")

    vm.send_key(str(boot_device))
    check_in_guest()
