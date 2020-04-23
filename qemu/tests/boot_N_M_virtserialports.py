import logging

from virttest import error_context
from virttest import utils_test
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Test guest with virtio-serial-device with multiple virtserialports
    Scenario 1:
        1.1. Boot a guest with 1 virtio-serial-bus with 3 serial ports
        1.2. Transfer data via every port
    Scenario 2:
        2.1. Start guest with 2 virtio-serial-pci,
        2.2. Each virtio-serial-pci has 3 virtio-serial-ports
        2.3. Transfer data via every port

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    os_type = params["os_type"]
    vm = env.get_vm(params['main_vm'])
    if os_type == "windows":
        driver_name = params["driver_name"]
        session = vm.wait_for_login()
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name)
        session.close()

    for port in params.objects("serials"):
        port_params = params.object_params(port)
        if not port_params['serial_type'].startswith('virtserial'):
            continue
        params['file_transfer_serial_port'] = port
        error_context.context("Transfer data with %s" % port, logging.info)
        transfer_data(params, vm, sender='both')
    vm.verify_alive()
    vm.verify_kernel_crash()
