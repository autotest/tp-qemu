import logging

from virttest import env_process, error_context, utils_disk, utils_misc, utils_test
from virttest.qemu_capabilities import Flags

LOG_JOB = logging.getLogger("avocado.test")


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
    for index in range(pci_bridge_num):
        params["pci_controllers"] += "pci_bridge%d " % index
        params["type_pci_bridge%d" % index] = "pci-bridge"


def prepare_images(test, params, image_num, pci_bridge_num, opr, device_num=0):
    """
    Prepare images attached to pci-bridge for guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param image_num: VM image number (except image1)
    :param pci_bridge_num: VM pci-bridge number
    :param opr: operation
    :param device_num: Prepared device number
    """
    pci_bridges = params.objects("pci_controllers")

    fmt_list = params.objects("disk_driver")
    for i in range(image_num):
        image = "stg%s" % i
        params["images"] = " ".join([params["images"], image])
        params["image_name_%s" % image] = "images/%s" % image
        params["image_size_%s" % image] = params["data_image_size"]
        params["force_create_image_%s" % image] = "yes"
        params["remove_image_%s" % image] = "yes"
        params["blk_extra_params_%s" % image] = "serial=TARGET_DISK%s" % i
        if opr != "hotplug_unplug":
            if i >= len(fmt_list):
                params["drive_format_%s" % image] = "virtio"
            else:
                params["drive_format_%s" % image] = fmt_list[i]
            d_format = params["drive_format_%s" % image]
            if d_format == "scsi-hd" and params["drive_format"] == "scsi-hd":
                params["drive_bus_%s" % image] = 1
            if d_format == "usb3":
                params["usbs"] += " xhci"
                params["usb_type_xhci"] = "nec-usb-xhci"
                content = "usbc_pci_bus_xhci"
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


def prepare_nics(test, params, pci_bridge_num, opr, device_num=0):
    """
    Prepare nics attached to pci-bridge for guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param pci_bridge_num: VM pci-bridge number
    :param opr: operation
    :param device_num: Prepared device number
    """
    pci_bridges = params.objects("pci_controllers")
    nic = params.objects("nics")[0]

    if opr != "hotplug_unplug":
        if pci_bridge_num == 1:
            if device_num >= 31:
                test.fail(
                    "There are already %d devices on %s" % (device_num, pci_bridges[0])
                )
            params["nic_pci_bus_%s" % nic] = pci_bridges[0]
        else:
            index = device_num % pci_bridge_num
            params["nic_pci_bus_%s" % nic] = pci_bridges[index]
        device_num += 1

    return device_num


def disk_hotplug(test, params, vm, session, image_name, drive_format, parent_bus):
    """
    Hotplug new disk.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    :param session: VM session
    :param image: Name of the new disk
    :param drive_format: Drive subsystem type (virtio, scsi, usb3)
    :param parent_bus: Bus(es), in which this device is plugged in
    """

    def check_usb_in_guest():
        """
        Check USB in guest
        """
        output = session.cmd(params["chk_usb_cmd"])
        return usb_serial in output  # pylint: disable=E0606

    if drive_format not in ("virtio", "scsi-hd", "usb3"):
        test.cancel("Unsupported drive format: %s" % drive_format)

    image_params = params.object_params(image_name)
    image_params["drive_format"] = drive_format
    devices = []

    if drive_format == "usb3":
        usbc_params = {"usb_type": "nec-usb-xhci"}
        devices = vm.devices.usbc_by_params(
            drive_format, usbc_params, pci_bus={"aobject": parent_bus}
        )

    devices += vm.devices.images_define_by_params(
        image_name,
        image_params,
        "disk",
        None,
        False,
        None,
        pci_bus={"aobject": parent_bus},
    )

    for dev in devices:
        ret = vm.devices.simple_hotplug(dev, vm.monitor)
        if ret[1] is False:
            test.fail("Failed to hotplug device '%s'." "Output:\n%s" % (dev, ret[0]))

    if drive_format == "usb3":
        usb_serial = params["blk_extra_params_%s" % image_name].split("=")[1]
        res = utils_misc.wait_for(
            check_usb_in_guest, timeout=360, text="Wait for getting usb device info"
        )
        if res is None:
            test.fail("Could not find the usb device serial:[%s]" % usb_serial)

    if drive_format == "virtio":
        return [devices[-1]]
    else:
        if Flags.BLOCKDEV in vm.devices.caps:
            return devices[::3]
        return devices[::2]


def check_data_disks(test, params, env, vm, session):
    """
    Check guest data disks (except image1)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    :param vm: VM object
    :param session: VM session
    """
    image_list = params.objects("images")
    del image_list[0]
    image_num = len(image_list)

    error_context.context("Check data disks in monitor!", LOG_JOB.info)
    monitor_info_block = vm.monitor.info_block(False)
    blocks = ",".join(monitor_info_block.keys())
    for image in image_list:
        if image not in blocks:
            test.fail("drive_%s is missed: %s!" % (image, blocks))

    error_context.context("Read and write on data disks!", LOG_JOB.info)
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
        iozone_cmd = params["iozone_cmd"]
        iozone_cmd = utils_misc.set_winutils_letter(session, iozone_cmd)
        data_image_size = params["data_image_size"]
        disks = utils_disk.get_windows_disks_index(session, data_image_size)
        disk_num = len(disks)
        if disk_num < image_num:
            err_msg = "set disk num: %d" % image_num
            err_msg += ", get in guest: %d" % disk_num
            test.fail("Fail to list all the volumes, %s" % err_msg)
        if not utils_disk.update_windows_disk_attributes(session, disks):
            test.fail("Failed to update windows disk attributes.")
        for disk in disks:
            drive_letter = utils_disk.configure_empty_disk(
                session, disk, data_image_size, os_type
            )
            if not drive_letter:
                test.fail("Fail to format disks.")
            iozone_cmd_disk = iozone_cmd % drive_letter[0]
            status, output = session.cmd_status_output(iozone_cmd_disk, timeout=3600)
            if status:
                test.fail(
                    "Check block device '%s' failed! Output: %s"
                    % (drive_letter[0], output)
                )
            utils_disk.clean_partition(session, disk, os_type)
    else:
        test.cancel("Unsupported OS type '%s'" % os_type)


@error_context.context_aware
def run(test, params, env):
    """
    [pci-bridge] Check devices which attached to 1 pci-bridge
    [pci-bridge] Check devices which attached to different pci-bridges
    [pci-bridge] Hotplug and unplug different devices to 1 pci-bridge
    [pci-bridge] Hotplug and unplug different devices to different pci-bridges
    [pci-bridge] Migration with pci-bridge
    This case will:
    1) Attach one or multiple pci-bridge(s) to guest.
    2) Prepare devices attached to pci-bridge(s).
    3) Start the guest.
    4) Hotplug devices (if needed).
    5) Check devices.
    6) Hotunplug devices (if needed).
    7) Do migration (if needed).

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Modify params!", test.log.info)
    pci_bridge_num = int(params.get("pci_bridge_num", 1))
    prepare_pci_bridge(test, params, pci_bridge_num)
    pci_bridges = params.objects("pci_controllers")

    opr = params.get("operation")
    image_num = int(params.get("image_num", 3))
    device_num = prepare_images(test, params, image_num, pci_bridge_num, opr)

    if opr != "block_stress":
        device_num = prepare_nics(test, params, pci_bridge_num, opr, device_num)

    params["start_vm"] = "yes"
    env_process.process_images(env_process.preprocess_image, test, params)
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    error_context.context("Get the main VM!", test.log.info)
    vm = env.get_vm(params["main_vm"])

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    if opr == "hotplug_unplug":
        device_list = []
        fmt_list = params.objects("disk_driver")
        image_list = params.objects("images")
        del image_list[0]
        if image_num > len(fmt_list):
            test.error("No sufficient disk driver type!")
        for i in range(image_num):
            image = image_list[i]
            fmt = fmt_list[i]
            if pci_bridge_num == 1:
                pci_bridge_id = pci_bridges[0]
            else:
                index = i % pci_bridge_num
                pci_bridge_id = pci_bridges[index]
            if fmt == "scsi-hd" and params["drive_format"] == "scsi-hd":
                params["drive_bus_%s" % image] = 1
            error_context.context(
                "Hotplug a %s disk on %s!" % (fmt, pci_bridge_id), test.log.info
            )
            device_list += disk_hotplug(
                test, params, vm, session, image, fmt, pci_bridge_id
            )

    check_data_disks(test, params, env, vm, session)

    error_context.context("Ping guest!", test.log.info)
    guest_ip = vm.get_address()
    status, output = utils_test.ping(guest_ip, count=10, timeout=20)
    if status:
        test.fail("Ping guest failed!")
    elif utils_test.get_loss_ratio(output) == 100:
        test.fail("All packets lost during ping guest %s." % guest_ip)

    if opr == "hotplug_unplug":
        error_context.context("Unplug those hotplugged devices!", test.log.info)
        device_list.reverse()
        for dev in device_list:
            ret = vm.devices.simple_unplug(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to unplug device '%s'." "Output:\n%s" % (dev, ret[0]))
    elif opr == "with_migration":
        error_context.context("Migrating...", test.log.info)
        vm.migrate(float(params.get("mig_timeout", "3600")))

    error_context.context("Check kernel crash message!", test.log.info)
    vm.verify_kernel_crash()

    session.close()
