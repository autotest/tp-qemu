import json
import os

from avocado.utils import process, wait
from virttest import error_context
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    Test QMP NBD server with Unix socket:
    1) Start QEMU with QMP monitor
    2) Enable QMP capabilities
    3) Start NBD server with Unix socket
    4) Connect to NBD server using netcat
    5) Stop NBD server
    6) Verify QMP monitor functionality and quit

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    nbd_unix_socket = params.get("nbd_unix_socket")

    # Clean up any existing socket
    if os.path.exists(nbd_unix_socket):
        os.unlink(nbd_unix_socket)

    # Start VM with QMP monitor
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    try:
        # Enable QMP capabilities
        error_context.context("Enable QMP capabilities", test.log.info)
        vm.monitor.cmd_qmp("qmp_capabilities")

        # Start NBD server
        error_context.context("Start NBD server", test.log.info)
        nbd_start_cmd = json.loads(params.get("nbd_server_start_cmd"))
        try:
            vm.monitor.cmd_qmp(nbd_start_cmd["execute"], nbd_start_cmd["arguments"])
        except QMPCmdError as e:
            test.fail("Failed to start NBD server: %s" % str(e))

        # Wait for socket to be created
        error_context.context("Wait for NBD socket to be created", test.log.info)
        if not wait.wait_for(lambda: os.path.exists(nbd_unix_socket), timeout=5):
            test.fail("NBD socket was not created")

        # Connect to NBD server using netcat
        error_context.context("Connect to NBD server", test.log.info)
        nbd_connect_cmd = params.get("nbd_connect_cmd")
        nc_process = process.SubProcess(nbd_connect_cmd, shell=True)
        nc_process.start()

        # Stop NBD server
        error_context.context("Stop NBD server", test.log.info)
        nbd_stop_cmd = json.loads(params.get("nbd_server_stop_cmd"))
        try:
            vm.monitor.cmd_qmp(nbd_stop_cmd["execute"], nbd_stop_cmd["arguments"])
        except QMPCmdError as e:
            test.fail("Failed to stop NBD server: %s" % str(e))

        # Stop netcat
        nc_process.terminate()

        # Verify QMP monitor functionality
        error_context.context("Verify QMP monitor functionality", test.log.info)
        qmp_quit_cmd = json.loads(params.get("qmp_quit_cmd"))
        try:
            response = vm.monitor.cmd_qmp(qmp_quit_cmd["execute"])
        except QMPCmdError as e:
            test.fail("Failed to execute quit command: %s" % str(e))

        # Check for expected shutdown message
        qmp_quit_msg = params.get("qmp_quit_msg")
        qmp_quit_reason = params.get("qmp_quit_reason")

        if qmp_quit_msg not in str(response):
            test.fail("Expected QMP shutdown message not found")
        if qmp_quit_reason not in str(response):
            test.fail("Expected QMP shutdown reason not found")

    finally:
        # Clean up
        if "nc_process" in locals() and nc_process.is_running():
            nc_process.terminate()
        if os.path.exists(nbd_unix_socket):
            os.unlink(nbd_unix_socket)
