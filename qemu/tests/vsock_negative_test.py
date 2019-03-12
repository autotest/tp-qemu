import random
import signal
import os
import logging

from avocado.utils import process

from virttest import utils_misc
from virttest import error_context

from qemu.tests import vsock_test


def check_data_received(test, rec_session, file):
    """
    Check if data is received successfully

    :param test: QEMU test object
    :param rec_session: nc-vsock receive session
    :param file: file to receive data
    """
    if not utils_misc.wait_for(lambda: rec_session.is_alive(),
                               timeout=3, step=0.1):
        test.error("Host connection failed.")
    if not utils_misc.wait_for(lambda: os.path.exists(file),
                               timeout=3, step=0.1):
        test.fail("Host does not create receive file successfully.")
    elif not utils_misc.wait_for(lambda: os.path.getsize(file) > 0,
                                 timeout=3, step=0.1):
        test.fail('Host does not receive data successfully.')


@error_context.context_aware
def kill_host_receive_process(test, rec_session):
    """
    Kill the receive process on host

    :param test: QEMU test object
    :param rec_session: nc-vsock receive session
    """
    error_context.context("Kill the nc-vsock process on host...",
                          logging.info)
    rec_session.kill(sig=signal.SIGINT)
    if not utils_misc.wait_for(lambda: not rec_session.is_alive(),
                               timeout=1, step=0.1):
        test.fail("Host nc-vsock process does not quit as expected.")


@error_context.context_aware
def run(test, params, env):
    """
    Vsock negative test

    1. Boot guest with vhost-vsock-pci device
    2. Download and compile nc-vsock on both guest and host
    S1):
    3. Connect guest CID(on host) without listening port inside guest
    S2):
    3. Send data from guest, nc-vsock -l $port < tmp_file
    4. Receive data from host, nc-vsock $guest_cid $port
    5. Interrupt nc-vsock process during transfering data on host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    nc_vsock_bin = vsock_test.compile_nc_vsock(test, vm, session)
    port = random.randrange(1, 6000)
    vsock_dev = params["vsocks"].split()[0]
    guest_cid = vm.devices.get(vsock_dev).get_param("guest-cid")
    nc_vsock_cmd = "%s %s %s" % (nc_vsock_bin, guest_cid, port)
    connected_str = "Connection reset by peer"
    error_context.context("Connect vsock from host without"
                          " listening on guest.", logging.info)
    try:
        process.system_output(nc_vsock_cmd)
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
        session, nc_vsock_bin, guest_cid, tmp_file, file_size=10000)
    try:
        check_data_received(test, rec_session, tmp_file)
        kill_host_receive_process(test, rec_session)
        vsock_test.check_guest_nc_vsock_exit(test, session)
    finally:
        session.cmd_output("rm -f %s" % tmp_file)
        session.close()
    vm.verify_alive()
