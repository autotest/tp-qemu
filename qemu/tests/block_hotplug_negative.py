import logging
import time

from virttest import data_dir
from virttest import storage
from virttest import error_context
from virttest.qemu_devices import qdevices


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest without block device.
    2) Hotplug a drive
    2) Hoplug block device with invalid blk params.
    3) Unplug the drive
    4) Hotplug the drive again
    5) Check vm is alive after drive unplug/hotplug

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def find_image(image_name):
        """
        Find the path of the iamge.

        :param image_name: name of image.
        :return mage_filename: filename of image.
        """
        image_params = params.object_params(image_name)
        image_filename = storage.get_image_filename(image_params, data_dir.get_data_dir())
        return image_filename

    def drive_unplug_plug(drive, vm):
        """
        Unplug drive then replug it.

        :param drive: instance of QRHDrive
        :param vm: Vitual Machine object
        """
        error_context.context("unplug the drive", logging.info)
        drive.unplug(vm.monitor)
        time.sleep(5)
        error_context.context("Hotplug the drive", logging.info)
        drive.hotplug(vm.monitor)

    img_list = params.get("images").split()
    img_format_type = params.get("img_format_type", "qcow2")
    pci_type = params.get("pci_type", "virtio-blk-pci")
    blk_num = int(params.get("blk_num", 1))
    add_block_device = True

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Hotplug block device", logging.info)
    for num in range(blk_num):
        device = qdevices.QDevice(pci_type)
        drive = qdevices.QRHDrive("block%d" % num)
        drive.set_param("file", find_image(img_list[num + 1]))
        drive.set_param("format", img_format_type)
        drive_id = drive.get_param("id")
        drive.hotplug(vm.monitor)
        #add controller if needed
        if params.get("need_controller", "no") == "yes":
            controller_model = params.get("controller_model")
            controller = qdevices.QDevice(controller_model)
            bus_extra_param = params.get("bus_extra_params_%s" % img_list[num + 1])
            if bus_extra_param:
                key, value = bus_extra_param.split("=")
                qdevice_params = {key: value}
                controller.params.update(qdevice_params)
            try:
                controller.hotplug(vm.monitor)
            except Exception as e:
                if "QMP command 'device_add' failed" in str(e):
                    logging.info("Failed to add controller with invalid params")
                    drive_unplug_plug(drive, vm)
                    add_block_device = False

        if add_block_device:
            device.set_param("drive", drive_id)
            device.set_param("id", "block%d" % num)
            blk_extra_param = params.get("blk_extra_params_%s" % img_list[num + 1])
            if blk_extra_param:
                key, value = blk_extra_param.split("=")
                device.set_param(key, value)
            try:
                device.hotplug(vm.monitor)
            except Exception as e:
                if "QMP command 'device_add' failed" in str(e):
                    logging.info("Failed to add block with invalid params")
                    drive_unplug_plug(drive, vm)

    error_context.context("Check vm is alive after drive unplug/hotplug test", logging.info)
    session = vm.wait_for_login()
    if not session.is_responsive():
        session.close()
        test.fail("VM can't work normally after drive unplug->hotplug")
    session.close()
