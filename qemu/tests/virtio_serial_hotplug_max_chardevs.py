import re
import time

from virttest import error_context, utils_misc, utils_test
from virttest.qemu_monitor import QMPCmdError

from qemu.tests import driver_in_use
from qemu.tests.virtio_console import add_chardev, add_virtio_ports_to_vm
from qemu.tests.virtio_serial_file_transfer import transfer_data
from qemu.tests.virtio_serial_hotplug_port_pci import get_buses_and_serial_devices


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug max chardevs on one virtio-serial-pci

    1. Boot a guest without any device
    2. Hotplug virtio-serial-pci
    3. Hotplug 31 chardevs
    4. Hotadd 30 virtserialports attached every one chardev
    5. Transfer data between guest and host via all ports
    6. Hotplug one existed chardev
    7. Hotplug one existed virtserialport
    8. Hot-unplug virtserialport
    9. Hot-unplug chardev

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def run_serial_data_transfer():
        """
        Transfer data via every virtserialport.
        """
        for serial_port in serials:
            port_params = params.object_params(serial_port)
            if not port_params["serial_type"].startswith("virtserial"):
                continue
            test.log.info("transfer data with port %s", serial_port)
            params["file_transfer_serial_port"] = serial_port
            transfer_data(params, vm, sender="both")

    def run_bg_test():
        """
        Set the operation of transferring data as background
        :return: return the background case thread if it's successful;
                 else raise error
        """
        stress_thread = utils_misc.InterruptedThread(run_serial_data_transfer)
        stress_thread.start()
        if not utils_misc.wait_for(
            lambda: driver_in_use.check_bg_running(vm, params), check_bg_timeout, 0, 1
        ):
            test.fail("Backgroud test is not alive!")
        return stress_thread

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    os_type = params["os_type"]
    check_bg_timeout = float(params.get("check_bg_timeout", 120))
    num_chardev = int(params.get("numberic_chardev"))
    num_serial_ports = int(params.get("virtio_serial_ports"))
    sleep_time = float(params.get("sleep_time", 0.5))
    for i in range(1, num_chardev):
        params["extra_chardevs"] += " channel%d" % i
        serial_name = "port%d" % (i - 1)
        params["extra_serials"] = "%s %s" % (
            params.get("extra_serials", ""),
            serial_name,
        )
        params["serial_type_%s" % serial_name] = "virtserialport"
    char_devices = add_chardev(vm, params)
    serials = params.objects("extra_serials")
    buses, serial_devices = get_buses_and_serial_devices(
        vm, params, char_devices, serials
    )
    vm.devices.simple_hotplug(buses[0], vm.monitor)
    for i in range(0, num_chardev):
        vm.devices.simple_hotplug(char_devices[i], vm.monitor)
        if i < num_serial_ports:
            vm.devices.simple_hotplug(serial_devices[i], vm.monitor)
            time.sleep(sleep_time)
    for device in serial_devices:
        add_virtio_ports_to_vm(vm, params, device)
    if os_type == "windows":
        driver_name = params["driver_name"]
        session = vm.wait_for_login()
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
    thread_transfer = run_bg_test()

    error_context.context("hotplug existed virtserialport and chardev", test.log.info)
    try:
        serial_devices[0].hotplug(vm.monitor, vm.devices.qemu_version)
    except QMPCmdError as e:
        if not re.search(
            "Duplicate (device |)ID '%s'" % serial_devices[0], str(e.data)
        ):
            msg = (
                "Should fail to hotplug device %s with error Duplicate"
                % serial_devices[0]
            )
            test.fail(msg)
    else:
        msg = "The device %s shoudn't be hotplugged successfully" % serial_devices[0]
        test.fail(msg)

    try:
        char_devices[0].hotplug(vm.monitor, vm.devices.qemu_version)
    except QMPCmdError as e:
        if not (
            "duplicate property '%s'" % char_devices[0] in str(e.data)
            or "'%s' already exists" % char_devices[0] in str(e.data)
        ):
            msg = (
                "Should fail to hotplug device %s with error Duplicate"
                % char_devices[0]
            )
            test.fail(msg)
    else:
        msg = "The device %s shoudn't be hotplugged successfully" % char_devices[0]
        test.fail(msg)

    thread_transfer.join()
    if not thread_transfer.is_alive():
        error_context.context(
            "hot-unplug all virtserialport and chardev", test.log.info
        )
        for i in range(0, num_chardev):
            if i < num_serial_ports:
                vm.devices.simple_unplug(serial_devices[i], vm.monitor)
            vm.devices.simple_unplug(char_devices[i], vm.monitor)
    vm.verify_kernel_crash()
