from virttest import env_process, error_context, utils_test

from provider import win_driver_utils
from qemu.tests.virtio_serial_file_transfer import transfer_data


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio serial guest file transfer with max ports.

    Steps:
    1) Boot up a VM with 30 virtserialports on one virtio-serial-pci.
    2) Transfer data via these ports one by one.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    num_serial_ports = int(params.get("virtio_serial_ports"))
    for i in range(2, num_serial_ports + 1):
        serial_name = "vs%d" % i
        params["serials"] = "%s %s" % (params.get("serials", ""), serial_name)
        params["serial_type_%s" % serial_name] = "virtserialport"
    params["start_vm"] = "yes"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    os_type = params["os_type"]

    if os_type == "windows":
        session = vm.wait_for_login()
        driver_name = params["driver_name"]
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        session.close()

    serials = params.objects("serials")
    for serial_port in serials:
        port_params = params.object_params(serial_port)
        if not port_params["serial_type"].startswith("virtserial"):
            continue
        test.log.info("transfer data with port %s", serial_port)
        params["file_transfer_serial_port"] = serial_port
        transfer_data(params, vm, sender="both")

    vm.verify_alive()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
    vm.destroy()
