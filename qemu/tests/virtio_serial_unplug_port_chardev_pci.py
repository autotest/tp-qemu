import time

from virttest import error_context, utils_test

from qemu.tests.hotplug_port_chardev_pci_with_console import get_virtio_serial_pci
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Test hot unplug virtio serial devices.

     1) Start guest with virtio serial device(s).
     2) Transfer data via serial port.
     3) Hot-unplug serial port
     4) Hot-unplug chardev device
     5) Hot-unplug virtio-serial-pci
     6) Hotplug virtio-serial-pci
     7) Hotplug chardev
     8) Hotplug the port
     9) Transfer data via port from guest to host
     10) Hot-unplug serial the port
     11) Hot-plug serial port to the same chardev.
     12) Transfer data via the port from host to guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    os_type = params["os_type"]
    sleep_time = float(params.get("sleep_time"))
    if os_type == "windows":
        sleep_time += 10
        driver_name = params["driver_name"]
        session = vm.wait_for_login()
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
    for port in params.objects("serials"):
        port_params = params.object_params(port)
        if not port_params["serial_type"].startswith("virt"):
            continue
        virtio_port = vm.devices.get(port)
        if not virtio_port:
            test.error("Virtio Port '%s' not found" % port)
        chardev_qid = virtio_port.get_param("chardev")
        try:
            port_chardev = vm.devices.get_by_qid(chardev_qid)[0]
        except IndexError:
            test.error("Failed to get device %s" % chardev_qid)
        params["file_transfer_serial_port"] = port
        virtio_serial_pci = get_virtio_serial_pci(vm, virtio_port)
        test.log.info("Transfer data with %s before hot-unplugging", port)
        transfer_data(params, vm, sender="both")
        vm.devices.simple_unplug(virtio_port, vm.monitor)
        vm.devices.simple_unplug(port_chardev, vm.monitor)
        vm.devices.simple_unplug(virtio_serial_pci, vm.monitor)
        time.sleep(sleep_time)
        vm.devices.simple_hotplug(virtio_serial_pci, vm.monitor)
        time.sleep(sleep_time)
        vm.devices.simple_hotplug(port_chardev, vm.monitor)
        vm.devices.simple_hotplug(virtio_port, vm.monitor)
        transfer_data(params, vm, sender="guest")
        vm.devices.simple_unplug(virtio_port, vm.monitor)
        vm.devices.simple_hotplug(virtio_port, vm.monitor)
        transfer_data(params, vm, sender="host")
    vm.verify_alive()
    vm.verify_kernel_crash()
