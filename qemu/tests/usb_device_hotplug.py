import logging

from virttest.qemu_devices import qdevices
from virttest import data_dir
from virttest import storage
from virttest import utils_misc


def run(test, params, env):
    """
    Test hotplug of usb devices.

    1) Boot up guest with usb block device
    2) verify the usb device
    2) Unplug the usb device and verify
    4) Hotplug the usb device and verify

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def _verify_usb_device_in_monitor(usb_type):
        """
        Verify the usb device in monitor.

        :param device_type: String usb device type.
        """
        logging.info("Check usb device information in monitor")
        output = str(vm.monitor.info("usb"))
        if params["product"] not in output:
            test.fail("Could not find %s" % usb_type)

    def _verify_usb_device_in_guest(session, device_serial):
        """
        Verify the usb device in guest.

        :param session:       Session object.
        :param device_serial: String usb device serial.
        """
        logging.info("Check usb device information in guest")

        # both Linux and Windows
        def _check_usb_info():
            output = session.cmd_output(params["chk_usb_info_cmd"],
                                        float(params["cmd_timeout"]))
            return (device_serial in output)
        res = utils_misc.wait_for(_check_usb_info,
                                  float(params["cmd_timeout"]),
                                  text="Wait for getting usb device info")
        if res is None:
            test.fail("Could not find the usb device serial:[%s]" %
                      device_serial)

        # Linux only
        if params.get("os_type") == "linux":
            drive_path = utils_misc.get_linux_drive_path(session,
                                                         device_serial)
            if not drive_path:
                test.error("Could not find [%s]" % drive_path)

            def _check_disk():
                output = session.cmd_output("fdisk -l",
                                            float(params["cmd_timeout"]))
                return (drive_path in output)
            res = utils_misc.wait_for(_check_disk,
                                      float(params["cmd_timeout"]),
                                      text="Wait for getting disk info")
            if res is None:
                test.fail("[%s] is not in disk partition table" %
                          drive_path)

    def _unplug_usb_device(usb_device):
        """
        Unplug the usb device and verify.

        :param usb_device: Qdevices object.
        """
        logging.info("Unplug usb device [%s]." % drive_name)
        usb_device.unplug(vm.monitor)
        ver_out = usb_device.verify_unplug("", vm.monitor)
        if not ver_out:
            test.fail("Unplug usb device [%s] failed" % drive_name)

    def _hotplug_usb_device(usb_device):
        """
        Hotplug the usb device and verify.

        :param usb_device: Qdevices object.
        """
        logging.info("Hotplug usb device [%s]." % drive_name)
        image_params = params.object_params(drive_name)
        image_path = storage.get_image_filename(image_params,
                                                data_dir.get_data_dir())
        drive = qdevices.QRHDrive(drive_name)
        drive.set_param("file", image_path)
        drive.set_param("format", params.get("img_format", "qcow2"))
        drive.hotplug(vm.monitor)

        usb_device.hotplug(vm.monitor)
        ver_out = usb_device.verify_hotplug("", vm.monitor)
        if not ver_out:
            test.fail("Hotplug usb device [%s] failed." % drive_name)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    _verify_usb_device_in_monitor(params["usb_type"])

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    # get the usb device and verify in the guest
    drive_name = params.objects("images")[-1]
    device_serial = params["blk_extra_params_%s" % drive_name].split("=")[1]
    _verify_usb_device_in_guest(session, device_serial)
    usb_device = vm.devices.get(drive_name)
    # unplug the device before repeating
    _unplug_usb_device(usb_device)

    for i in xrange(int(params.get("repeat_times", 1))):
        logging.info("Hotplug (iteration %s)" % (i + 1))
        _hotplug_usb_device(usb_device)
        # verify usb device after hotplug
        _verify_usb_device_in_monitor(params["usb_type"])
        _verify_usb_device_in_guest(session, device_serial)
        _unplug_usb_device(usb_device)

    session.close()
