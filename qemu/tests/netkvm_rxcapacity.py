import re

from virttest import error_context, utils_misc, utils_net, utils_test
from virttest.utils_windows import virtio_win


@error_context.context_aware
def run(test, params, env):
    """
    Test netkvm RX capacity with different RX queue sizes.

    This test verifies that the RX queue size setting in QEMU matches
    the reported RxQueueSize in Windows guest when MaxRxBuffers is set.

    Test steps:
    1) Boot VM with specific rx_queue_size parameter
    2) Set Init.MaxRxBuffers parameter using netkvmco.exe
    3) Verify the parameter was set correctly
    4) Check RxQueueSize using netkvm-wmi.cmd
    5) Verify RxQueueSize matches expected value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def set_and_verify_rxcapacity(session, vm, test, value):
        """
        Set RxCapacity parameter and verify it was set correctly.

        :param session: VM session info
        :param vm: QEMU test object
        :param test: QEMU test object
        :param value: Value to set for RxCapacity
        """
        error_context.context(f"Setting RxCapacity to {value}", test.log.info)
        utils_net.set_netkvm_param_value(vm, "RxCapacity", value)

        current_value = utils_net.get_netkvm_param_value(vm, "RxCapacity")
        if current_value != value:
            test.fail(
                f"Failed to set RxCapacity. Expected: {value}, Got: {current_value}"
            )
        test.log.info("Successfully set RxCapacity to %s", value)

    def get_rxqueue_size_from_wmi(session, test, netkvm_wmi_path, wmi_cmd_copy_cmd):
        """
        Get RxQueueSize from netkvm-wmi.cmd output.

        :return: RxQueueSize value as integer
        """
        wmi_cmd_copy_cmd = utils_misc.set_winutils_letter(session, wmi_cmd_copy_cmd)
        session.cmd(wmi_cmd_copy_cmd, timeout=30)

        error_context.context("Getting RxQueueSize from WMI", test.log.info)
        wmi_output = session.cmd_output(f"{netkvm_wmi_path} cfg", timeout=30)
        test.log.info("WMI output:\n%s", wmi_output)

        rx_queue_pattern = r"RxQueueSize=(\d+)"
        match = re.search(rx_queue_pattern, wmi_output)
        if not match:
            test.fail("Could not find RxQueueSize in WMI output")

        rx_queue_size = int(match.group(1))
        test.log.info("Found RxQueueSize: %s", rx_queue_size)
        return rx_queue_size

    timeout = params.get_numeric("login_timeout", 360)
    expected_rx_queue_size = params.get_numeric("expected_rx_queue_size")
    rx_capacity_value = params.get("rx_capacity_value", "1024")
    netkvm_wmi_path = params.get("netkvm_wmi_path", "C:\\netkvm-wmi.cmd")
    wmi_cmd_copy_cmd = params.get("wmi_cmd_copy_cmd")

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=timeout)

    virtio_win.prepare_netkvmco(vm)
    try:
        set_and_verify_rxcapacity(session, vm, test, rx_capacity_value)
        actual_rx_queue_size = get_rxqueue_size_from_wmi(
            session, test, netkvm_wmi_path, wmi_cmd_copy_cmd
        )
        error_context.context(
            f"Verifying RxQueueSize. Expected: {expected_rx_queue_size}, "
            f"Actual: {actual_rx_queue_size}",
            test.log.info,
        )

        if actual_rx_queue_size != expected_rx_queue_size:
            test.fail(
                f"RxQueueSize mismatch. Expected: {expected_rx_queue_size}, "
                f"Got: {actual_rx_queue_size}"
            )

        test.log.info(
            "SUCCESS: RxQueueSize %s matches expected value %s",
            actual_rx_queue_size,
            expected_rx_queue_size,
        )

        error_context.context("Testing network connectivity", test.log.info)
        status, output = utils_net.ping(
            "223.5.5.5", count=10, timeout=60, session=session
        )
        if status:
            test.fail(f"Ping test failed: {output}")

        package_lost = utils_test.get_loss_ratio(output)
        if package_lost != 0:
            test.fail(f"Ping test shows {package_lost}% packet loss")

        test.log.info("Network connectivity test passed")

    finally:
        session.close()
