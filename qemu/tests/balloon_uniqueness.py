from virttest import env_process
from virttest.qemu_devices.qdevices import QDevice
from virttest.qemu_monitor import QMPCmdError
from virttest.virt_vm import VMCreateError


def run(test, params, env):
    """
    Boot guest with or hotplug more than 1 balloon devices, qemu should reject,
    3 scenarios:
    1. Boot guest with two balloons
    2. Boot guest with one balloon and then hot plug the second one
    3. Boot guest with none balloon and then hot plug 2 balloon devices

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    error_msg = params.get("error_msg")
    num_boot_devices = len(params.objects("balloon"))
    try:
        env_process.preprocess_vm(test, params, env, vm_name)
    except VMCreateError as e:
        if num_boot_devices < 2 or error_msg not in e.output:
            raise
    else:
        if num_boot_devices > 1:
            test.fail("The guest should not start with two balloon devices.")

    machine_type = params["machine_type"]
    bus = {"aobject": "pci.0"}
    if "s390" in machine_type:  # For s390x platform
        model = "virtio-balloon-ccw"
        bus = {"type": "virtual-css"}
    else:
        model = "virtio-balloon-pci"
    num_hotplug_devices = int(params.get("num_hotplug_devices", 0))
    for i in range(num_hotplug_devices):
        dev = QDevice(model, parent_bus=bus)
        dev.set_param("id", "hotplugged_balloon%s" % i)
        dev_num = len(params.objects("balloon")) + i
        try:
            vm = env.get_vm(vm_name)
            vm.devices.simple_hotplug(dev, vm.monitor)
        except QMPCmdError as e:
            if dev_num < 1:
                test.fail("Fail to hotplug the balloon device: %s" % str(e))
            elif error_msg not in e.data["desc"]:
                raise
        else:
            if dev_num >= 1:
                test.fail("Qemu should reject the second balloon device.")
