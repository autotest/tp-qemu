from virttest import error_context, qemu_monitor, utils_test

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Add existed virtio serial port and serial bus
    1) Start guest with virtio-serial-port and virtio-serial-pci
    2) Hot-plug existed virtio-serial-port
    3) Hot plug existed virtio-serial-pci
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    if params["os_type"] == "windows":
        utils_test.qemu.windrv_check_running_verifier(session, vm, test, "vioser", 300)
    session.close()
    port = params.objects("serials")[1]
    virtio_port = vm.devices.get(port)
    pci_dev_id = virtio_port.params["bus"].split(".")[0]
    pci_dev = vm.devices.get(pci_dev_id)
    try:
        virtio_port.hotplug(vm.monitor, vm.devices.qemu_version)
    except qemu_monitor.QMPCmdError as e:
        if "Duplicate" not in e.data["desc"]:
            test.fail(e.data["desc"])
    else:
        test.fail("hotplugg virtserialport device should be failed")
    try:
        pci_dev.hotplug(vm.monitor, vm.devices.qemu_version)
    except qemu_monitor.QMPCmdError as e:
        if "Duplicate" not in e.data["desc"]:
            test.fail(e.data["desc"])
    else:
        test.fail("hotplugg virtio-serial-pci device should be failed")

    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
