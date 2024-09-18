from virttest import error_context, utils_test

from qemu.tests.virtio_console import add_chardev, add_virtio_ports_to_vm
from qemu.tests.virtio_serial_file_transfer import transfer_data
from qemu.tests.virtio_serial_hotplug_port_pci import get_buses_and_serial_devices


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug virtio-serial-pci and chardev and virtserialport

    1. Boot a guest without any device
    2. Hot plug virtio-serial-bus
    3. Hot add chardev 1
    4. Hot plug serial port on chardev 1
    5. Transfer data from host to guest via port
    6. Transfer data from guest to host via port

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    os_type = params["os_type"]
    char_devices = add_chardev(vm, params)
    serials = params.objects("extra_serials")
    buses, serial_devices = get_buses_and_serial_devices(
        vm, params, char_devices, serials
    )
    vm.devices.simple_hotplug(buses[0], vm.monitor)
    vm.devices.simple_hotplug(char_devices[0], vm.monitor)
    vm.devices.simple_hotplug(serial_devices[0], vm.monitor)
    for device in serial_devices:
        add_virtio_ports_to_vm(vm, params, device)
    if os_type == "windows":
        driver_name = params["driver_name"]
        session = vm.wait_for_login()
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
    params["file_transfer_serial_port"] = serials[0]
    transfer_data(params, vm, sender="both")
