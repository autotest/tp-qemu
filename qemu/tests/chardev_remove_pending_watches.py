import aexpect
from virttest import error_context, utils_test
from virttest.utils_virtio_port import VirtioPortTest

from qemu.tests.virtio_serial_file_transfer import generate_data_file


@error_context.context_aware
def run(test, params, env):
    """
    Remove pending watches after virtserialport unplug.

     1) Start guest with virtio serial device(s).
     2) Open the chardev on the host
     3) Send 2g file from guest to host
     4) Hot-unplug the port on the host
     5) After step 4, read transferred data on host
     6) Guest has no crash or panic

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    os_type = params["os_type"]
    file_size = params.get_numeric("filesize")
    guest_dir = params.get("guest_script_folder", "/var/tmp/")
    port_name = params["file_transfer_serial_port"]

    virtio_test = VirtioPortTest(test, env, params)
    (vm, guest_worker, port) = virtio_test.get_vm_with_single_port()
    port.open()
    session = vm.wait_for_login()
    guest_file_name = generate_data_file(guest_dir, file_size, session)
    if os_type == "windows":
        vport_name = "\\\\.\\" + port_name
        guest_file_name = guest_file_name.replace("/", "")
        guest_send_cmd = "copy %s > con %s" % (guest_file_name, vport_name)
        driver_name = params["driver_name"]
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
    else:
        vport_name = "/dev/virtio-ports/%s" % port_name
        guest_send_cmd = "cat %s > %s" % (guest_file_name, vport_name)

    try:
        session.cmd(guest_send_cmd)
    # large data transfer won't exit because of small ringbuf
    except aexpect.ShellTimeoutError:
        pass

    try:
        port_unplug = vm.devices.get(port_name)
        vm.devices.simple_unplug(port_unplug, vm.monitor)
        if port.sock.recv(4096) is None:
            test.fail("Host can't receive data !")
    finally:
        clean_cmd = params["clean_cmd"]
        port.close()
        session.cmd("%s %s" % (clean_cmd, guest_file_name))
        session.close()
    vm.verify_alive()
    vm.verify_kernel_crash()
