from virttest import env_process, error_context
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    unplug chardevs while guest attached with isa-serial (RHEL and x86 only):
    isa-device could not hotplug&un-plug,so just regard it as negative testing
    1) Start guest with isa-serial with pty
    2) login guest and do some operation
    3) Try to un-plug chardevs device from isa-device
    4) repeat step 1 to 3 with udp, tcp.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    serial_id = params.objects("serials")[-1]
    params["start_vm"] = "yes"
    for backend in ["unix_socket", "tcp_socket", "pty"]:
        params["chardev_backend_%s" % serial_id] = backend
        vm = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        serial_device = vm.devices.get(serial_id)
        chardev_qid = serial_device.get_param("chardev")
        chardev_device = vm.devices.get_by_qid(chardev_qid)[0]
        try:
            chardev_device.unplug(vm.monitor)
        except QMPCmdError as e:
            if e.data["desc"] != "Chardev '%s' is busy" % chardev_qid:
                test.fail("It is not the expected error")
        else:
            test.fail("Should not be unplug successfully")
        vm.verify_kernel_crash()
        vm.destroy()
