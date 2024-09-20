from virttest import env_process, error_context
from virttest.utils_virtio_port import VirtioPortTest


@error_context.context_aware
def run(test, params, env):
    """
    Induce throttling by opening chardev but not reading data from it:
    1) Start guest with virtio-serial with unix option
    2) On the host, open the chardev but don't read from it
    3) In the guest, write to the virtio-serial port.
    4) transfer data from host to guest but do not read in guest
    5) repeat step 1 to 4 with tcp option.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    @error_context.context_aware
    def send_data_from_guest_to_host():
        session = vm.wait_for_login()
        port.open()
        error_context.context("send data from guest to host", test.log.info)
        if params["os_type"] == "windows":
            vport_name = "\\\\.\\Global\\" + port.name
            cmd = "dd if=/dev/zero of=%s bs=1024 count=1" % vport_name
        else:
            cmd = "dd if=/dev/zero of=/dev/virtio-ports/%s bs=1024 count=1" % port.name
        session.cmd(cmd)
        session.close()

    @error_context.context_aware
    def send_data_from_host_to_guest():
        port.open()
        error_context.context("send data from host to guest", test.log.info)
        data = "Hello world \n" * 100
        data = data.encode()
        port.sock.send(data)
        guest_worker.cmd("virt.open('%s')" % port.name)

    serial_id = params.objects("serials")[-1]
    try:
        virtio_test = VirtioPortTest(test, env, params)
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port()
        vm.verify_alive()
        send_data_from_guest_to_host()
        send_data_from_host_to_guest()
        vm.verify_alive()
    finally:
        virtio_test.cleanup()
    vm.destroy()
    params["chardev_backend_%s" % serial_id] = "tcp_socket"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    try:
        virtio_test = VirtioPortTest(test, env, params)
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port()
        vm.verify_alive()
        send_data_from_guest_to_host()
        send_data_from_host_to_guest()
        vm.verify_alive()
    finally:
        virtio_test.cleanup()
