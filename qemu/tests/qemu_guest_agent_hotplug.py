import time

from virttest import error_context
from virttest.qemu_devices import qdevices

from qemu.tests.qemu_guest_agent import run as guest_agent_run


@error_context.context_aware
def run(test, params, env):
    """
    hotplug guest agent device

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_status_unplug(out, dev):
        if out is True:
            test.log.debug("Unplug %s successfully", dev)
        else:
            test.fail("Error occurred while unpluging %s" % dev)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    params["backend_char_plug"]
    char_id = params["id_char_plug"]
    gagent_name = params["gagent_name"]
    char_path = vm.get_serial_console_filename(gagent_name)
    params["path_char_plug"] = char_path
    dev_driver = params["dev_driver"]
    dev_id = params["dev_id"]
    error_context.context("hotplug guest agent device", test.log.info)
    params_char_plug = params.object_params("char_plug")
    chardev = qdevices.CharDevice(params=params_char_plug)
    chardev.hotplug(vm.monitor, vm.devices.qemu_version)
    device = qdevices.QDevice(dev_driver)
    device.set_param("chardev", char_id)
    device.set_param("id", dev_id)
    device.set_param("name", gagent_name)
    device.hotplug(vm.monitor, vm.devices.qemu_version)

    error_context.context("install and start guest agent", test.log.info)
    guest_agent_run(test, params, env)

    error_context.context("hot unplug guest agent device", test.log.info)
    device.unplug(vm.monitor)
    device_status = device.verify_unplug("", vm.monitor)
    check_status_unplug(device_status, "virtserialport")
    time.sleep(3)
    chardev.unplug(vm.monitor)
    chardev_status = chardev.verify_unplug("", vm.monitor)
    check_status_unplug(chardev_status, "socket")
    vm.verify_alive()
