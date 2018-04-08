import logging

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test usb host device passthrough

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    @error_context.context_aware
    def usb_dev_hotplug():
        error_context.context("Plugin usb device", logging.info)
        session.cmd_status("dmesg -c")
        vm.monitor.cmd(monitor_add)
        session.cmd_status("sleep 2")
        session.cmd_status("udevadm settle")
        messages_add = session.cmd("dmesg -c")
        for line in messages_add.splitlines():
            logging.debug("[dmesg add] %s" % line)
        if messages_add.find(match_add) == -1:
            test.fail("kernel didn't detect plugin")

    @error_context.context_aware
    def usb_dev_verify():
        error_context.context("Check usb device %s in guest" % device,
                              logging.info)
        session.cmd(lsusb_cmd)

    @error_context.context_aware
    def usb_dev_unplug():
        error_context.context("Unplug usb device", logging.info)
        vm.monitor.cmd(monitor_del)
        session.cmd_status("sleep 2")
        messages_del = session.cmd("dmesg -c")
        for line in messages_del.splitlines():
            logging.debug("[dmesg del] %s" % line)
        if messages_del.find(match_del) == -1:
            test.fail("kernel didn't detect unplug")

    if params.get("usb_negative_test", "no") != "no":
        # Negative test.
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login()
        usb_host_device_list = params["usb_host_device_list"].split(",")
        for dev in usb_host_device_list:
            vid, pid = dev.split(":")
            monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
            monitor_add += ",vendorid=%s" % vid
            monitor_add += ",productid=%s" % pid
            reply = vm.monitor.cmd(monitor_add)
            usb_reply_msg_list = params.get("usb_reply_msg").split(";")
            negative_flag = False
            for msg in usb_reply_msg_list:
                if msg in reply:
                    negative_flag = True
                    break
            if not negative_flag:
                test.fail("Could not get expected warning"
                          " msg in negative test, monitor"
                          " returns: '%s'" % reply)
        vm.reboot()
        return

    device = params["usb_host_device"]
    (vendorid, productid) = device.split(":")

    # compose strings
    lsusb_cmd = "lsusb -v -d %s" % device
    monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
    monitor_add += ",vendorid=0x%s" % vendorid
    monitor_add += ",productid=0x%s" % productid
    monitor_del = "device_del usbhostdev"
    match_add = "New USB device found, "
    match_add += "idVendor=%s, idProduct=%s" % (vendorid, productid)
    match_del = "USB disconnect"

    error_context.context("Check usb device %s on host" % device, logging.info)
    try:
        process.system(lsusb_cmd)
    except:
        test.cancel("Device %s not present on host" % device)

    error_context.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    repeat_times = int(params.get("usb_repeat_times", "1"))
    for i in range(repeat_times):
        if params.get("usb_check_isobufs", "no") == "no":
            error_context.context("Hotplug (iteration %i)" % (i + 1),
                                  logging.info)
        else:
            # The value of isobufs could only be in '4, 8, 16'
            isobufs = (2 << (i % 3 + 1))
            monitor_add = "device_add usb-host,bus=usbtest.0,id=usbhostdev"
            monitor_add += ",vendorid=0x%s" % vendorid
            monitor_add += ",productid=0x%s" % productid
            monitor_add += ",isobufs=%d" % isobufs
            error_context.context("Hotplug (iteration %i), with 'isobufs'"
                                  " option set to %d" % ((i + 1), isobufs),
                                  logging.info)
        usb_dev_hotplug()
        usb_dev_verify()
        usb_dev_unplug()

    session.close()
