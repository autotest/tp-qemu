import logging
from autotest.client.shared import error
from virttest.utils_test import qemu
from avocado.core import exceptions


@error.context_aware
def run(test, params, env):
    """
    KVM usb device hotlpuging test:
    1) Log into a guest
    2) Verify if usb device can be hotplug and unplug

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 600))
    session = vm.wait_for_login(timeout=timeout)
    usb_device = qemu.UsbDevTest(test, params, env)
    driver = params.get("usb_type")
    repeat_times = int(params.get("repeat_times"))
    logging.info("Hot plug and unplug usb device")
    for i in xrange(repeat_times):
        if driver == 'usb-storage':
            drive = usb_device.drive_set('udev')
            drive.hotplug(vm.monitor)
            dev = usb_device.device_set('udev', driver)
        else:
            dev = usb_device.device_set('udev', driver, drive=None)
        usb_device.device_add(dev, driver)
        exist = usb_device.check_usb_dev_guest(driver,
                                               session,
                                               params.get("vp_id"),
                                               params.get("vendor"),
                                               params.get("product"))
        if exist:
            logging.info("The %s device was found in guest,hotpluging success" %
                         driver)
        else:
            raise exceptions.TestFail("Could not find '%s' in guest" % driver)
        usb_device.device_del(dev, driver)
        exist = usb_device.check_usb_dev_guest(driver,
                                               session,
                                               params.get("vp_id"),
                                               params.get("vendor"),
                                               params.get("product"))
        if exist:
            raise exceptions.TestFail("Still could find '%s' in guest" % driver)
        else:
            logging.info("The %s device couldn't found in guest,\
                         hotunpluging success" % driver)
