from virttest import error_context
from virttest import utils_test

from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest with virtio-serial-device with multiple virtserialport

    1. Boot a guest with 1 virtio-serial-bus with 3 serial ports
    2. Transfer data from host to guest via port2, port3
    3. Transfer data from guest to host via port2, port3

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    os_type = params["os_type"]
    vm = env.get_vm(params["main_vm"])
    driver_name = params["driver_name"]
    session = vm.wait_for_login()
    if os_type == "windows":
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name)
    for port in params.objects("serials")[2:]:
        port_params = params.object_params(port)
        if not port_params['serial_type'].startswith('virt'):
            continue
        params['file_transfer_serial_port'] = port
        transfer_data(params, vm, sender='both')
    vm.verify_kernel_crash()
