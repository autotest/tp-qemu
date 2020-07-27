import re
import logging

from avocado.utils import process

from virttest import error_context
from virttest.qemu_devices import qdevices
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    Test usb host device passthrough

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def get_usb_host_dev():
        device_list = []
        for device in vm.devices:
            if isinstance(device, qdevices.QDevice):
                if device.get_param("driver") == "usb-host":
                    device_list.append(device)
        return device_list

    def get_vendorid_productid(bus, addr):
        out = process.getoutput("lsusb -v -s %s:%s" % (bus, addr))
        res = re.search(r"idVendor\s+0x(\w+).*idProduct\s+0x(\w+)", out, re.S)
        return (res.group(1), res.group(2))

    @error_context.context_aware
    def usb_dev_hotplug(dev):
        error_context.context("Hotplug usb-host device", logging.info)
        session.cmd_status("dmesg -c")
        vm.devices.simple_hotplug(dev, vm.monitor)
        session.cmd_status("sleep 2")
        session.cmd_status("udevadm settle")
        messages_add = session.cmd("dmesg -c")
        for line in messages_add.splitlines():
            logging.debug("[dmesg add] %s" % line)
        if messages_add.find(match_add) == -1:
            test.fail("kernel didn't detect plugin")

    @error_context.context_aware
    def usb_dev_verify():
        error_context.context("Check usb device in guest", logging.info)
        session.cmd(lsusb_cmd)

    @error_context.context_aware
    def usb_dev_unplug(dev):
        error_context.context("Unplug usb-host device", logging.info)
        session.cmd("dmesg -c")
        vm.devices.simple_unplug(dev, vm.monitor)
        session.cmd_status("sleep 2")
        messages_del = session.cmd("dmesg -c")
        for line in messages_del.splitlines():
            logging.debug("[dmesg del] %s" % line)
        if messages_del.find(match_del) == -1:
            test.fail("kernel didn't detect unplug")

    usb_params = {}

    if params.get("usb_negative_test", "no") != "no":
        # Negative test.
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login()
        usb_reply_msg_list = params.get("usb_reply_msg").split(";")
        usb_host_device_list = params["usb_host_device_list"].split(",")
        for dev in usb_host_device_list:
            vid, pid = dev.split(":")
            usb_params["vendorid"] = vid
            usb_params["productid"] = pid
            dev = qdevices.QDevice("usb-host", usb_params)
            try:
                vm.devices.simple_hotplug(dev, vm.monitor)
            except QMPCmdError as detail:
                logging.warn(detail)
                for msg in usb_reply_msg_list:
                    if msg in detail.data['desc']:
                        break
                else:
                    test.fail("Could not get expected warning"
                              " msg in negative test, monitor"
                              " returns: '%s'" % detail)
            else:
                test.fail("Hotplug operation in negative test"
                          " should not succeed.")
        return

    usb_hostdev = params["usb_devices"].split()[-1]
    usb_options = params.get("options")
    if usb_options == "with_vendorid_productid":
        vendorid = params["usbdev_option_vendorid_%s" % usb_hostdev]
        productid = params["usbdev_option_productid_%s" % usb_hostdev]
        usb_params["vendorid"] = "0x%s" % vendorid
        usb_params["productid"] = "0x%s" % productid
    elif usb_options == "with_hostbus_hostaddr":
        hostbus = params["usbdev_option_hostbus_%s" % usb_hostdev]
        hostaddr = params["usbdev_option_hostaddr_%s" % usb_hostdev]
        usb_params["hostbus"] = hostbus
        usb_params["hostaddr"] = hostaddr
        (vendorid, productid) = get_vendorid_productid(hostbus, hostaddr)

    lsusb_cmd = "lsusb -v -d %s:%s" % (vendorid, productid)
    match_add = "New USB device found, "
    match_add += "idVendor=%s, idProduct=%s" % (vendorid, productid)
    match_del = "USB disconnect"

    error_context.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    usb_dev_verify()
    usb_devs = get_usb_host_dev()
    for dev in usb_devs:
        usb_dev_unplug(dev)

    repeat_times = int(params.get("usb_repeat_times", "1"))
    for i in range(repeat_times):
        msg = "Hotplug (iteration %d)" % (i+1)
        usb_params["id"] = "usbhostdev%s" % i
        if params.get("usb_check_isobufs", "no") == "yes":
            # The value of isobufs could only be in '4, 8, 16'
            isobufs = (2 << (i % 3 + 1))
            usb_params["isobufs"] = isobufs
            msg += ", with 'isobufs' option set to %d." % isobufs
        error_context.context(msg, logging.info)
        usb_dev = qdevices.QDevice("usb-host", usb_params)
        usb_dev_hotplug(usb_dev)
        usb_dev_verify()
        usb_dev_unplug(usb_dev)

    session.close()
