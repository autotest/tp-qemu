import logging
import re

from virttest import error_context
from virttest import utils_test
from virttest import utils_misc
from virttest.utils_virtio_port import VirtioPortTest
from qemu.tests.virtio_driver_sign_check import get_driver_file_path


@error_context.context_aware
def run(test, params, env):
    """
    virtio serial test for windows vm:
    1) Boot guest with virtioserialport;
    2) Transefer data from guest to host;
    3) Transefer data from host to guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def transfer_from_host_to_guest(port):
        """
        Transfer data from host to guest via serial port and check result.

        :param port: virtio serialport used to transfer data
        """

        port.open()
        port.sock.setblocking(0)
        port.sock.sendall(transfer_data)
        output = session.cmd_output(guest_receive_cmd)
        if not re.findall(guest_pattern, output, re.M):
            test.fail("Guest fails to receive data, output is: %s" % output)
        port.close()

    def transfer_from_guest_to_host(port):
        """
        Transfer data from guest to host via serial port and check result.

        :param port: virtio serialport used to transfer data
        """

        port.open()
        port.sock.setblocking(0)
        output = session.cmd_output(guest_send_cmd)
        if params.get("check_from_guest", "no") == "yes":
            if not re.findall(guest_pattern, output, re.M):
                test.fail("Guest fails to send data, output is %s" % output)
        else:
            try:
                tmp = port.sock.recv(1024)[:-1]
            except IOError as failure_detail:
                logging.warn("Got err while recv: %s", failure_detail)
            if tmp != transfer_data:
                test.fail("Incorrect data: '%s' != '%s'" % (transfer_data, tmp))
        port.close()

    vm = env.get_vm(params["main_vm"])
    driver_name = params["driver_name"]
    data = params["data"]
    transfer_data = data.encode()
    path = params["path"]
    guest_pattern = params["guest_pattern"]
    guest_receive_cmd = params["guest_receive_cmd"]
    guest_send_cmd = params["guest_send_cmd"]

    if path == "virtio-win":
        session = vm.wait_for_login()
        viowin_letter, path = get_driver_file_path(session, params)
        guest_receive_cmd = guest_receive_cmd % path
        guest_send_cmd = guest_send_cmd % path
    elif path == "WIN_UTILS":
        session = vm.wait_for_serial_login()
        guest_receive_cmd = utils_misc.set_winutils_letter(session,
                                                           guest_receive_cmd)
        guest_send_cmd = utils_misc.set_winutils_letter(session, guest_send_cmd)

    session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                            test, driver_name)
    port = VirtioPortTest(test, env, params).get_virtio_ports(vm)[1][0]

    error_context.context("Tranfer data from host to guest", logging.info)
    transfer_from_host_to_guest(port)

    error_context.context("Tranfer data from guest to host", logging.info)
    transfer_from_guest_to_host(port)
