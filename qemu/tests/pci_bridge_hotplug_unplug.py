import logging

from virttest import error_context
from virttest import env_process
from virttest import utils_test
from virttest import utils_misc


def prepare_pci_bridge(test, params, pci_bridge_num):
    """
    Prepare pci-bridge for guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param pci_bridge_num: VM pci-bridge number
    """
    if pci_bridge_num < 1:
        test.cancel("There should be at least one pci-bridge!")

    params["pci_controllers"] = ""
    for index in xrange(pci_bridge_num):
        params["pci_controllers"] += "pci_bridge%d " % index
        params["type_pci_bridge%d" % index] = "pci-bridge"


def prepare_images(test, params, image_num, device_num):
    """
    Prepare images attached to pci-bridge for guest

    :param params: Dictionary with the test parameters
    :param image_num: VM image number (except image1)
    :param device_num: Prepared device number
    """
    pci_bridges = params.objects("pci_controllers")
    pci_bridge_num = len(pci_bridges)
    if pci_bridge_num < 1:
        test.cancel("There should be at least one pci-bridge!")

    fmt_list = params.objects("disk_driver")
    for i in xrange(image_num):
        image = "stg%s" % i
        params["images"] = ' '.join([params["images"], image])
        params["image_name_%s" % image] = "images/%s" % image
        params["image_size_%s" % image] = "1G"
        params["force_create_image_%s" % image] = "yes"
        params["remove_image_%s" % image] = "yes"
        params["blk_extra_params_%s" % image] = "serial=TARGET_DISK%s" % i
        if params.get("need_hotplug", "no") == "no":
            if i >= len(fmt_list):
                params["drive_format_%s" % image] = "virtio"
            else:
                params["drive_format_%s" % image] = fmt_list[i]
            if params["drive_format_%s" % image] == "usb2":
                params["usbs"] += " ehci"
                params["usb_type_ehci"] = "usb-ehci"
                content = "usbc_pci_bus_ehci"
            else:
                content = "disk_pci_bus_%s" % image
            if pci_bridge_num == 1:
                params[content] = pci_bridges[0]
            else:
                index = i % pci_bridge_num
                params[content] = pci_bridges[index]
        else:
            params["boot_drive_%s" % image] = "no"
        device_num = device_num + 1

    return device_num


def check_disks(test, params, env, vm, session):
    """
    Check guest disks (except image1)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    :param vm: VM object
    :param session: VM session
    """
    image_list = params.objects("images")
    del image_list[0]
    image_num = len(image_list)

    error_context.context("Check disks in monitor!", logging.info)
    monitor_info_block = vm.monitor.info_block(False)
    blocks = ','.join(monitor_info_block.keys())
    for image in image_list:
        if image not in blocks:
            test.fail("drive_%s is missed: %s!" % (image, blocks))

    error_context.context("Read and write data on all disks!",
                          logging.info)
    os_type = params["os_type"]
    if os_type == "linux":
        sub_test_type = params.get("sub_test_type", "dd_test")
        for image in image_list:
            params["dd_if"] = "ZERO"
            params["dd_of"] = image
            utils_test.run_virt_sub_test(test, params, env, sub_test_type)

            params["dd_if"] = image
            params["dd_of"] = "NULL"
            utils_test.run_virt_sub_test(test, params, env, sub_test_type)
    elif os_type == "windows":
        cmd_timeout = int(params.get("cmd_timeout", 3600))
        disk_index = params.objects("disk_index")
        disk_letter = params.objects("disk_letter")
        fmt_list = params.objects("disk_driver")
        for num in range(image_num):
            utils_misc.format_windows_disk(session, disk_index[num],
                                           mountpoint=disk_letter[num])
            iozone_cmd = params.get("iozone_cmd") % disk_letter[num]
            iozone_cmd = utils_misc.set_winutils_letter(session, iozone_cmd)
            status, output = session.cmd_status_output(iozone_cmd,
                                                       timeout=cmd_timeout)
            if status:
                test.fail("Check '%s' block device '%s' failed! Output: %s"
                          % (fmt_list[num], disk_letter[num], output))
    else:
        test.cancel("Unsupported OS type '%s'" % os_type)


def disk_hotplug(test, params, vm, session, image_name,
                 drive_format, parent_bus):
    """
    Hotplug new disk.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    :param session: VM session
    :param image: Name of the new disk
    :param drive_format: Drive subsystem type (virtio, scsi, usb2)
    :param parent_bus: Bus(es), in which this device is plugged in
    """
    def check_usb_in_guest():
        """
        Check USB in guest
        """
        output = session.cmd(params["chk_usb_cmd"])
        return (usb_serial in output)

    if drive_format not in ('virtio', 'scsi-hd', 'usb2'):
        raise NotImplementedError()

    image_params = params.object_params(image_name)
    image_params["drive_format"] = drive_format
    devices = []

    if drive_format == 'usb2':
        usbc_params = {'usb_type': 'usb-ehci'}
        devices = vm.devices.usbc_by_params(drive_format,
                                            usbc_params,
                                            pci_bus={'aobject': parent_bus})

    devices += vm.devices.images_define_by_params(image_name, image_params, 'disk',
                                                  None, False, None,
                                                  pci_bus={'aobject': parent_bus})

    for device in devices:
        vm.devices.insert(device)
        device.hotplug(vm.monitor)

    ver_out = devices[-1].verify_hotplug("", vm.monitor)
    if not ver_out:
        test.fail("%s disk is not in qtree after hotplug!" % drive_format)

    if drive_format == 'usb2':
        usb_serial = params["blk_extra_params_%s" % image_name].split("=")[1]
        res = utils_misc.wait_for(check_usb_in_guest, timeout=360,
                                  text="Wait for getting usb device info")
        if res is None:
            test.fail("Could not find the usb device serial:[%s]" % usb_serial)

    if drive_format == 'virtio':
        return [devices[-1]]
    else:
        return devices[::2]


@error_context.context_aware
def run(test, params, env):
    """
    [pci-bridge] Hotplug and unplug different devices to 1 pci-bridge
    [pci-bridge] Hotplug and unplug different devices to different pci-bridges
    This case will:
    1) Attach one or multiple pci-bridge(s) to guest.
    2) Prepare disks.
    3) Start the guest.
    4) Hotplug different devices to pci-bridge(s).
    5) Check devices.
    6) Hot-unplug devices.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Modify params!", logging.info)
    pci_bridge_num = int(params.get("pci_bridge_num", 1))
    prepare_pci_bridge(test, params, pci_bridge_num)
    pci_bridges = params.objects("pci_controllers")

    device_num = 0
    image_num = int(params.get("image_num", 3))
    if (image_num < 1):
        test.cancel("No pre-prepared images for hotplugging!")
    else:
        device_num = prepare_images(test, params, image_num, device_num)

    params["start_vm"] = "yes"
    env_process.process_images(env_process.preprocess_image, test, params)
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    device_list = []
    fmt_list = params.objects("disk_driver")
    image_list = params.objects("images")
    del image_list[0]
    for i in range(image_num):
        if i >= len(fmt_list):
            test.error("No sufficient disk driver type!")
        if pci_bridge_num == 1:
            pci_bridge_id = pci_bridges[0]
        else:
            index = i % pci_bridge_num
            pci_bridge_id = pci_bridges[index]
        error_context.context("Hotplug a %s disk on %s!"
                              % (fmt_list[i], pci_bridge_id), logging.info)
        device_list += disk_hotplug(test, params, vm, session,
                                    image_list[i], fmt_list[i], pci_bridge_id)

    check_disks(test, params, env, vm, session)

    error_context.context("Unplug those hotplugged devices!", logging.info)
    device_list.reverse()
    for dev in device_list:
        dev.unplug(vm.monitor)
        dev.verify_unplug("", vm.monitor)

    error_context.context("Check kernel crash message!", logging.info)
    vm.verify_kernel_crash()

    vm.destroy()
