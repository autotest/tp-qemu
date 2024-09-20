from virttest import error_context

from qemu.tests.virtio_console import add_chardev, add_virtio_ports_to_vm
from qemu.tests.virtio_serial_file_transfer import transfer_data
from qemu.tests.virtio_serial_hotplug_port_pci import get_buses_and_serial_devices


def get_virtio_serial_pci(vm, serial_device):
    """
    Get virtio-serial-pci id

    :param vm: VM object to be operated
    :param serial_device: serial device
    :return: virtio-serial-pci id
    """
    serial_device_bus = serial_device.get_param("bus")
    serial_bus_id = serial_device_bus.split(".")[0]
    return vm.devices.get(serial_bus_id)


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug chardev and virtserialport

    1. Boot a guest with 1 virtconsole attached to pty backend
    2. Hot plug unix_socket backend
    3. Hot add virtserialport, attached on unix chardev
    4. Transfer data between host and guest via virtserialport
    5. Hot-unplug existed virt-serial-pci, this should success without crash

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    char_devices = add_chardev(vm, params)
    serials = params.objects("extra_serials")
    serial_devices = get_buses_and_serial_devices(vm, params, char_devices, serials)[1]
    vm.devices.simple_hotplug(char_devices[0], vm.monitor)
    vm.devices.simple_hotplug(serial_devices[0], vm.monitor)
    for device in serial_devices:
        add_virtio_ports_to_vm(vm, params, device)
    params["file_transfer_serial_port"] = serials[0]
    transfer_data(params, vm, sender="both")
    if params.get("unplug_pci") == "yes":
        virtio_serial_pci = get_virtio_serial_pci(vm, serial_devices[0])
        vm.devices.simple_unplug(virtio_serial_pci, vm.monitor)
    vm.verify_kernel_crash()
