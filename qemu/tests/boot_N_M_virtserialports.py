from virttest import env_process, error_context, utils_test

from provider import win_driver_utils
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
    if params.get("start_vm") == "no":
        num_bus = params.get_numeric("numberic_bus")
        for i in range(2, num_bus + 1):
            serial_name = "vs%d" % i
            params["serials"] = "%s %s" % (params.get("serials", ""), serial_name)
            params["serial_type_%s" % serial_name] = "virtserialport"
            params["serial_bus_%s" % serial_name] = "<new>"
        params["start_vm"] = "yes"
        env_process.preprocess(test, params, env)

    vm = env.get_vm(params["main_vm"])
    os_type = params["os_type"]
    if os_type == "windows":
        driver_name = params["driver_name"]
        session = vm.wait_for_login()
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        session.close()

    for port in params.objects("serials"):
        port_params = params.object_params(port)
        if not port_params["serial_type"].startswith("virtserial"):
            continue
        params["file_transfer_serial_port"] = port
        error_context.context("Transfer data with %s" % port, test.log.info)
        transfer_data(params, vm, sender="both")
    vm.verify_alive()
    vm.verify_kernel_crash()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
