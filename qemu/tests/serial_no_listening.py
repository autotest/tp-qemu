import aexpect
from avocado.utils import process
from virttest import error_context, utils_test

from provider import win_driver_utils
from qemu.tests.virtio_serial_file_transfer import get_virtio_port_property


@error_context.context_aware
def run(test, params, env):
    """
    Writing to a virtio serial port while no listening side.
    1) boot guest with serial device.
    2) host send while no listening side.
    3) guest send while no listening side.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    timeout = params.get("timeout", 60)
    os_type = params["os_type"]
    vm = env.get_vm(params["main_vm"])
    driver_name = params["driver_name"]
    guest_send_cmd = params["guest_send_cmd"]

    session = vm.wait_for_login()
    if os_type == "windows":
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
    port_path = get_virtio_port_property(vm, params["file_transfer_serial_port"])[1]

    error_context.context("host send while no listening side", test.log.info)
    host_send_cmd = 'echo "hi" | nc -U %s' % port_path
    try:
        process.system(host_send_cmd, shell=True, timeout=timeout)
    except process.CmdError:
        pass
    else:
        test.fail("Host send should fail while no listening side")

    error_context.context("guest send while no listening side", test.log.info)
    try:
        output = session.cmd_output(guest_send_cmd)
    except aexpect.ShellTimeoutError:
        if os_type != "linux":
            test.error("timeout when guest send command:  %s" % guest_send_cmd)
    else:
        if not (
            os_type == "windows"
            and ("The system cannot write to the specified device" in output)
        ):
            test.fail("Guest send should fail while no listening side")

    vm.verify_kernel_crash()

    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
