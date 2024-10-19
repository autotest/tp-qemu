from virttest import env_process, error_context
from virttest.qemu_monitor import QMPCmdError

from provider import win_driver_utils
from qemu.tests.virtio_console import (
    add_chardev,
    add_virtio_ports_to_vm,
    add_virtserial_device,
)
from qemu.tests.virtio_serial_file_transfer import transfer_data


def get_buses_and_serial_devices(vm, params, char_devices, serials):
    """
    Get buses list and serial devices list

    :param vm: VM object to be operated
    :param params: test params for the device
    :param char_devices: CharDevice list
    :param serials: serial device
    :return: buses list and serial device object list
    """
    buses = []
    serial_devices = []
    for index, serial_id in enumerate(serials):
        chardev_id = char_devices[index].get_qid()
        params["serial_name_%s" % serial_id] = serial_id
        devices = add_virtserial_device(vm, params, serial_id, chardev_id)
        for device in devices:
            if device.child_bus:
                buses.append(device)
            else:
                serial_devices.append(device)
    return buses, serial_devices


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug virtio-serial-pci and virtserialport

    1. Boot a guest with 2 chardev, no serial port & no pci
    2. Hot plug virtio-serial-bus
    3. Hot add virtserialport, attached on chardev 1
    4. Hot plug another serial port on chardev 2 with "nr=1", should fail
    5. Hot plug the serial port again with "nr=2"
    6. Transfer data between guest and host via port1 and port2
    7. Reboot/system_reset/shudown guest after hotplug(optional)
    8. Transfer data between guest and host via port1 and port2
    9. Hot-unplug relative port1 and port2
    10. Hot-unplug virtio-serial-bus
    11. Reboot/system_reset/shudown/migration guest after hot-unplug(optional)
    12. Repeat step 2 to step 10 100 times

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def run_interrupt_test(interrupt_test):
        """
        Run interrupt test(reboot/shutdown/migration) after hot plug/unplug.

        :param interrupt_test: reboot/shutdown/migration test
        """

        session = vm.wait_for_login()
        globals().get(interrupt_test)(test, params, vm, session)
        session.close()

    def run_serial_data_transfer():
        """
        Transfer data between two ports.
        """

        params["file_transfer_serial_port"] = serials[0]
        transfer_data(params, vm, sender="host")
        params["file_transfer_serial_port"] = serials[1]
        transfer_data(params, vm, sender="guest")

    params["serials"] = params.objects("serials")[0]
    repeat_times = int(params.get("repeat_times", 1))
    interrupt_test_after_plug = params.get("interrupt_test_after_plug")
    interrupt_test_after_unplug = params.get("interrupt_test_after_unplug")
    vm = env.get_vm(params["main_vm"])
    char_devices = add_chardev(vm, params)
    for device in char_devices:
        extra_params = " " + device.cmdline()
        params["extra_params"] = params.get("extra_params", "") + extra_params
    params["start_vm"] = "yes"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    # Make sure the guest boot successfully before hotplug
    vm.wait_for_login()
    vm.devices.insert(char_devices)
    serials = params.objects("extra_serials")
    buses, serial_devices = get_buses_and_serial_devices(
        vm, params, char_devices, serials
    )
    for i in range(repeat_times):
        error_context.context(
            "Hotplug/unplug serial devices the %s time" % (i + 1), test.log.info
        )
        vm.devices.simple_hotplug(buses[0], vm.monitor)
        vm.devices.simple_hotplug(serial_devices[0], vm.monitor)
        pre_nr = serial_devices[0].get_param("nr")

        # Try hotplug different device with same 'nr'
        if params.get("plug_same_nr") == "yes":
            serial_devices[1].set_param("bus", serial_devices[0].get_param("bus"))
            serial_devices[1].set_param("nr", pre_nr)
            try:
                serial_devices[1].hotplug(vm.monitor, vm.devices.qemu_version)
            except QMPCmdError as e:
                if "A port already exists at id %d" % pre_nr not in str(e.data):
                    test.fail("Hotplug fail for %s, not as expected" % str(e.data))
            else:
                test.fail('Hotplug with same "nr" option success while should fail')
            serial_devices[1].set_param("nr", int(pre_nr) + 1)
        vm.devices.simple_hotplug(serial_devices[1], vm.monitor)
        for device in serial_devices:
            add_virtio_ports_to_vm(vm, params, device)

        run_serial_data_transfer()

        if interrupt_test_after_plug:
            test.log.info("Run %s after hotplug", interrupt_test_after_plug)
            run_interrupt_test(interrupt_test_after_plug)
            if not vm.is_alive():
                return
            run_serial_data_transfer()

        if params.get("unplug_pci") == "yes":
            vm.devices.simple_unplug(serial_devices[0], vm.monitor)
            vm.devices.simple_unplug(serial_devices[1], vm.monitor)
            out = vm.devices.simple_unplug(buses[0], vm.monitor)
            if out[1] is False:
                msg = "Hot-unplug device %s failed" % buses[0]
                test.fail(msg)
            if interrupt_test_after_unplug:
                test.log.info("Run %s after hot-unplug", interrupt_test_after_unplug)
                run_interrupt_test(interrupt_test_after_unplug)

    if params.get("memory_leak_check", "no") == "yes":
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            if params.get("unplug_pci") == "yes":
                vm.devices.simple_hotplug(buses[0], vm.monitor)
                vm.devices.simple_hotplug(serial_devices[0], vm.monitor)
            win_driver_utils.memory_leak_check(vm, test, params)
