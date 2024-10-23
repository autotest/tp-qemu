from virttest import error_context

from qemu.tests.virtio_console import add_chardev


@error_context.context_aware
def run(test, params, env):
    """
    Hot-plug Various chardev

    1. Boot a guest without chardev, no serial port & no pci
    2. Hot plug Unix chardev backend
    3. Hot plug udp chardev backend
    4. Hot plug null backend
    5. Hot plug file backend
    6. Hot plug pty backend
    7. Hot plug ringbuf backend
    8. Write data to ringbuf
    9. Read data from ringbuf
    10. Hot-unplug Unix chardev backend
    11. Hot-unplug udp chardev backend
    12. Hot-unplug null backend
    13. Hot-unplug file backend
    14. Hot-unplug pty backend
    15. Hot-unplug ringbuf backend


    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def cmd_qmp_log(vm, cmd, args):
        reply = vm.monitor.cmd_qmp(cmd, args)
        if "error" in reply:
            if reply["error"]["class"] == "CommandNotFound":
                test.error("qmp command %s not supported" % cmd)
            else:
                test.error("qmp error: %s" % reply["error"]["desc"])
        return reply

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    char_devices = add_chardev(vm, params)
    for char_device in char_devices:
        vm.devices.simple_hotplug(char_device, vm.monitor)
        chardev_id = char_device.get_qid()
        chardev_param = params.object_params(chardev_id)
        backend = chardev_param.get("chardev_backend", "unix_socket")
        if backend == "ringbuf":
            ringbuf_write_size = int(params.get("ringbuf_write_size"))
            ringbuf_read_size = int(params.get("ringbuf_read_size"))
            if ringbuf_write_size < ringbuf_read_size:
                test.error(
                    "data error:write_size %d must above read_size %d"
                    % (ringbuf_write_size, ringbuf_read_size)
                )
            ringbuf_data = params.get("ringbuf_data")
            ringbuf_format = params.get("ringbuf_format")
            cmd_qmp_log(
                vm,
                "ringbuf-write",
                {"device": chardev_id, "data": ringbuf_data, "format": ringbuf_format},
            )
            ringbuf_read = cmd_qmp_log(
                vm,
                "ringbuf-read",
                {
                    "device": chardev_id,
                    "size": ringbuf_read_size,
                    "format": ringbuf_format,
                },
            )
            if ringbuf_data[:ringbuf_read_size] != ringbuf_read["return"]:
                test.fail(
                    "qmp error: can't find data '%s' in %s"
                    % (ringbuf_data[:ringbuf_read_size], ringbuf_read)
                )
    for char_device in char_devices:
        vm.devices.simple_unplug(char_device, vm.monitor)
    vm.reboot()
