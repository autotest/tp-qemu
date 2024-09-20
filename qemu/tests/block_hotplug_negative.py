import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest without block device.
    2) Hotplug a drive
    3) Hotplug block device with invalid blk params.
    4) Unplug the drive
    5) Hotplug the drive again
    6) Check vm is alive after drive unplug/hotplug

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def drive_unplug_plug(drive, vm):
        """
        Unplug drive then replug it.

        :param drive: instance of QRHDrive
        :param vm: Vitual Machine object
        """
        error_context.context("unplug the drive", test.log.info)
        drive.unplug(vm.monitor)
        time.sleep(5)
        error_context.context("Hotplug the drive", test.log.info)
        drive.hotplug(vm.monitor, vm.devices.qemu_version)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Hotplug block device", test.log.info)
    img_list = params.get("images").split()
    image_name = img_list[-1]
    image_params = params.object_params(image_name)
    devs = vm.devices.images_define_by_params(image_name, image_params, "disk")
    drive = devs[-2]
    for dev in devs:
        try:
            vm.devices.simple_hotplug(dev, vm.monitor)
        except Exception as e:
            if "QMP command 'device_add' failed" in str(e):
                test.log.info("Failed to hotplug device with invalid params")
                try:
                    drive_unplug_plug(drive, vm)
                except Exception as e:
                    test.fail("Failed to hotplug/unplug drive with error:" "%s") % e

    error_context.context(
        "Check vm is alive after drive unplug/hotplug test", test.log.info
    )
    session = vm.wait_for_login()
    if not session.is_responsive():
        session.close()
        test.fail("VM can't work normally after drive unplug->hotplug")
    session.close()
