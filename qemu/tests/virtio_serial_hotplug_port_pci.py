from virttest import error_context
from virttest import env_process
from virttest.qemu_monitor import QMPCmdError

from qemu.tests.virtio_console import add_chardev
from qemu.tests.virtio_console import add_virtserial_device
from qemu.tests.virtio_console import add_virtio_ports_to_vm
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug virtio-serial-pci and virtserialport

    1. Boot a guest with 2 chardev, no serial port & no pci
    2. Hot plug virtio-serial-bus
    3. Hot add virtserialport, attached on chardev 1
    4. Hot plug another serial port on chardev 2 with "nr=1", should fail
    5. Hot plug the serial port again with "nr=2"
    6. Transfer data from host to guest via port1
    7. Transfer data from guest to host via port2

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    params['serials'] = params.objects('serials')[0]
    vm = env.get_vm(params['main_vm'])
    char_devices = add_chardev(vm, params)
    for device in char_devices:
        extra_params = ' ' + device.cmdline()
        params['extra_params'] = params.get('extra_params', '') + extra_params
    params['start_vm'] = "yes"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params['main_vm'])
    vm.devices.insert(char_devices)
    serials = params.objects('extra_serials')
    buses = []
    serial_devices = []
    for index, serial_id in enumerate(serials):
        chardev_id = char_devices[index].get_qid()
        params['serial_name_%s' % serial_id] = serial_id
        devices = add_virtserial_device(vm, params, serial_id, chardev_id)
        for device in devices:
            if device.child_bus:
                buses.append(device)
            else:
                serial_devices.append(device)
    vm.devices.simple_hotplug(buses[0], vm.monitor)
    vm.devices.simple_hotplug(serial_devices[0], vm.monitor)
    pre_nr = serial_devices[0].get_param('nr')
    # Try hotplug different device with same 'nr'
    serial_devices[1].set_param('bus', serial_devices[0].get_param('bus'))
    serial_devices[1].set_param('nr', pre_nr)
    try:
        serial_devices[1].hotplug(vm.monitor)
    except QMPCmdError as e:
        if 'A port already exists at id %d' % pre_nr not in str(e.data):
            test.fail('Hotplug fail for %s, not as expected' % str(e.data))
    else:
        test.fail('Hotplug with same "nr" option success while should fail')
    serial_devices[1].set_param('nr', int(pre_nr) + 1)
    vm.devices.simple_hotplug(serial_devices[1], vm.monitor)
    for device in serial_devices:
        add_virtio_ports_to_vm(vm, params, device)
    params['file_transfer_serial_port'] = serials[0]
    transfer_data(params, vm, sender='host')
    params['file_transfer_serial_port'] = serials[1]
    transfer_data(params, vm, sender='guest')
