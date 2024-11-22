import os
import random
import signal

from avocado.utils import path, process
from virttest import error_context, utils_misc

from qemu.tests import vsock_test


def check_data_received(test, rec_session, file):
    """
    Check if data is received successfully

    :param test: QEMU test object
    :param rec_session: vsock receive session
    :param file: file to receive data
    """
    if not utils_misc.wait_for(lambda: rec_session.is_alive(), timeout=20, step=1):
        test.error("Host connection failed.")
    if not utils_misc.wait_for(lambda: os.path.exists(file), timeout=20, step=1):
        test.fail("Host does not create receive file successfully.")
    elif not utils_misc.wait_for(
        lambda: os.path.getsize(file) > 0, timeout=300, step=5
    ):
        test.fail("Host does not receive data successfully.")


@error_context.context_aware
def kill_host_receive_process(test, rec_session):
    """
    Kill the receive process on host

    :param test: QEMU test object
    :param rec_session: vsock receive session
    """
    error_context.context("Kill the vsock process on host...", test.log.info)
    rec_session.kill(sig=signal.SIGINT)
    if not utils_misc.wait_for(lambda: not rec_session.is_alive(), timeout=1, step=0.1):
        test.fail("Host vsock process does not quit as expected.")


@error_context.context_aware
def run(test, params, env):
    """
    Vsock negative test

    1. Boot guest with vhost-vsock-pci device
    2. Download and compile vsock on both guest and host
    3. Connect guest CID(on host) without listening port inside guest
    3. Send data from guest
    4. Receive data from host
    5. Interrupt vsock process during transfering data on host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    vsock_test_tool = params["vsock_test_tool"]
    if vsock_test_tool == "nc_vsock":
        tool_bin = vsock_test.compile_nc_vsock(test, vm, session)
    if vsock_test_tool == "ncat":
        tool_bin = path.find_command("ncat")
    port = random.randrange(1, 6000)
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    conn_cmd = None
    if vsock_test_tool == "nc_vsock":
        conn_cmd = "%s %s %s" % (tool_bin, guest_cid, port)
    if vsock_test_tool == "ncat":
        conn_cmd = "%s --vsock %s %s" % (tool_bin, guest_cid, port)
    if conn_cmd is None:
        raise ValueError(f"unexpected test tool: {vsock_test_tool}")
    connected_str = "Connection reset by peer"
    error_context.context(
        "Connect vsock from host without" " listening on guest.", test.log.info
    )
    try:
        process.system_output(conn_cmd)
    except process.CmdError as e:
        if connected_str not in str(e.result):
            test.fail("The connection does not fail as expected.")
    else:
        test.fail("The connection success, while it is expected to fail.")
    finally:
        session.close()

    session = vm.wait_for_login()
    tmp_file = "/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)
    rec_session = vsock_test.send_data_from_guest_to_host(
        session, tool_bin, guest_cid, tmp_file
    )
    try:
        check_data_received(test, rec_session, tmp_file)
        kill_host_receive_process(test, rec_session)
        vsock_test.check_guest_vsock_conn_exit(test, session)
    finally:
        session.cmd_output("rm -f %s" % tmp_file)
        session.close()
    vm.verify_alive()
