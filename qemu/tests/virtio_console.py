"""
Collection of virtio_console and virtio_serialport tests.

:copyright: 2010-2012 Red Hat Inc.
"""

import array
import logging
import os
import random
import re
import select
import socket
import threading
import time
from collections import deque
from subprocess import Popen

from avocado.utils import process
from virttest import (
    env_process,
    error_context,
    funcatexit,
    qemu_virtio_port,
    utils_misc,
)
from virttest.qemu_devices import qcontainer, qdevices
from virttest.utils_test.qemu import migration
from virttest.utils_virtio_port import VirtioPortTest

LOG_JOB = logging.getLogger("avocado.test")


EXIT_EVENT = threading.Event()


def __set_exit_event():
    """
    Sets global EXIT_EVENT
    :note: Used in cleanup by funcatexit in some tests
    """
    LOG_JOB.warning("Executing __set_exit_event()")
    EXIT_EVENT.set()


def add_chardev(vm, params):
    """
    Generate extra CharDevice without serial device utilize it

    :param vm: VM object to be operated
    :param params: Dictionary with the test parameters
    :return list of added CharDevice object
    """
    qemu_binary = utils_misc.get_qemu_binary(params)
    qdevices = qcontainer.DevContainer(
        qemu_binary,
        vm.name,
        params.get("strict_mode"),
        params.get("workaround_qemu_qmp_crash"),
        params.get("allow_hotplugged_vm"),
    )
    char_devices = params["extra_chardevs"].split()
    host = params.get("chardev_host", "127.0.0.1")
    free_ports = utils_misc.find_free_ports(5000, 6000, len(char_devices), host)
    device_list = []
    for index, chardev in enumerate(char_devices):
        chardev_param = params.object_params(chardev)
        file_name = vm.get_serial_console_filename(chardev)
        backend = chardev_param.get("chardev_backend", "unix_socket")
        if backend in ["udp", "tcp_socket"]:
            chardev_param["chardev_host"] = host
            chardev_param["chardev_port"] = str(free_ports[index])
        device = qdevices.chardev_define_by_params(chardev, chardev_param, file_name)
        device_list.append(device)
    return device_list


def add_virtserial_device(vm, params, serial_id, chardev_id):
    """
    Generate extra serial devices individually, without CharDevice

    :param vm: VM object to be operated
    :param params: Dictionary with the test parameters
    :return list of added serial devices
    """
    s_params = params.object_params(serial_id)
    serial_type = s_params["serial_type"]
    machine = params.get("machine_type")
    if "-mmio" in machine:
        controller_suffix = "device"
    elif machine.startswith("s390"):
        controller_suffix = "ccw"
    else:
        controller_suffix = "pci"
    bus_type = "virtio-serial-%s" % controller_suffix
    return vm.devices.serials_define_by_variables(
        serial_id,
        serial_type,
        chardev_id,
        bus_type,
        s_params.get("serial_name"),
        s_params.get("serial_bus"),
        s_params.get("serial_nr"),
        s_params.get("serial_reg"),
    )


def add_virtio_ports_to_vm(vm, params, serial_device):
    """
    Add serial device to vm.virtio_ports

    :param vm: VM object to be operated
    :param params: Dictionary with the test parameters
    :param serial_device: serial device object
    """
    serial_id = serial_device.get_qid()
    chardev_id = serial_device.get_param("chardev")
    chardev = vm.devices.get(chardev_id)
    filename = chardev.get_param("path")
    chardev_params = params.object_params(chardev_id)
    backend = chardev_params.get("chardev_backend", "unix_socket")
    if backend in ["udp", "tcp_socket"]:
        filename = (chardev.get_param("host"), chardev.get_param("port"))
    serial_name = serial_device.get_param("name")
    vm.virtio_ports.append(
        qemu_virtio_port.VirtioSerial(serial_id, serial_name, filename, backend)
    )


@error_context.context_aware
def run(test, params, env):
    """
    KVM virtio_console test

    This test contain multiple tests. The name of the executed test is set
    by 'virtio_console_test' cfg variable. Main function with the set name
    with prefix 'test_' thus it's easy to find out which functions are
    tests and which are helpers.

    Every test has it's own cfg parameters, please see the actual test's
    docstring for details.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    virtio_test = VirtioPortTest(test, env, params)

    def get_virtio_serial_name():
        if params.get("machine_type").startswith("arm64-mmio"):
            return "virtio-serial-device"
        elif params.get("machine_type").startswith("s390"):
            return "virtio-serial-ccw"
        else:
            return "virtio-serial-pci"

    #
    # Smoke tests
    #
    def test_open():
        """
        Try to open virtioconsole port.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        guest_worker.cmd("virt.open('%s')" % (port.name))
        port.open()
        virtio_test.cleanup(vm, guest_worker)

    def test_multi_open():
        """
        Try to open the same port twice.
        :note: On linux it should pass with virtconsole and fail with
               virtserialport. On Windows booth should fail
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        guest_worker.cmd("virt.close('%s')" % (port.name), 10)
        guest_worker.cmd("virt.open('%s')" % (port.name), 10)
        (match, data) = guest_worker._cmd("virt.open('%s')" % (port.name), 10)
        # Console on linux is permitted to open the device multiple times
        if port.is_console == "yes" and guest_worker.os_linux:
            if match != 0:  # Multiple open didn't pass
                test.fail(
                    "Unexpected fail of opening the console"
                    " device for the 2nd time.\n%s" % data
                )
        else:
            if match != 1:  # Multiple open didn't fail:
                test.fail(
                    "Unexpended pass of opening the"
                    " serialport device for the 2nd time."
                )
        port.open()
        virtio_test.cleanup(vm, guest_worker)

    def test_close():
        """
        Close the socket on the guest side
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        guest_worker.cmd("virt.close('%s')" % (port.name), 10)
        port.close()
        virtio_test.cleanup(vm, guest_worker)

    def test_polling():
        """
        Test correct results of poll with different cases.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        # Poll (OUT)
        port.open()
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLOUT), 2)

        # Poll (IN, OUT)
        port.sock.sendall(b"test")
        for test in [select.POLLIN, select.POLLOUT]:
            guest_worker.cmd("virt.poll('%s', %s)" % (port.name, test), 10)

        # Poll (IN HUP)
        # I store the socket informations and close the socket
        port.close()
        for test in [select.POLLIN, select.POLLHUP]:
            guest_worker.cmd("virt.poll('%s', %s)" % (port.name, test), 10)

        # Poll (HUP)
        guest_worker.cmd("virt.recv('%s', 4, 1024, False)" % (port.name), 10)
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLHUP), 2)

        # Reconnect the socket
        port.open()
        # Redefine socket in consoles
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLOUT), 2)
        virtio_test.cleanup(vm, guest_worker)

    def test_sigio():
        """
        Test whether virtio port generates sigio signals correctly.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        if port.is_open():
            port.close()
            time.sleep(0.5)  # wait for SIGHUP to be emitted

        # Enable sigio on specific port
        guest_worker.cmd("virt.asynchronous('%s', True, 0)" % (port.name), 10)

        # Test sigio when port open
        guest_worker.cmd(
            "virt.set_pool_want_return('%s', select.POLLOUT)" % (port.name), 10
        )
        port.open()
        match, data = guest_worker._cmd(
            "virt.get_sigio_poll_return('%s')" % (port.name), 10
        )
        if match == 1:
            test.fail("Problem with HUP on console port:\n%s" % data)

        # Test sigio when port receive data
        guest_worker.cmd(
            "virt.set_pool_want_return('%s', select.POLLOUT |"
            " select.POLLIN)" % (port.name),
            10,
        )
        port.sock.sendall(b"0123456789")
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test sigio port close event
        guest_worker.cmd(
            "virt.set_pool_want_return('%s', select.POLLHUP |"
            " select.POLLIN)" % (port.name),
            10,
        )
        port.close()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test sigio port open event and persistence of written data on port.
        guest_worker.cmd(
            "virt.set_pool_want_return('%s', select.POLLOUT |"
            " select.POLLIN)" % (port.name),
            10,
        )
        port.open()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test event when erase data.
        guest_worker.cmd("virt.clean_port('%s')" % (port.name), 10)
        port.close()
        guest_worker.cmd(
            "virt.set_pool_want_return('%s', select.POLLOUT)" % (port.name), 10
        )
        port.open()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Disable sigio on specific port
        guest_worker.cmd("virt.asynchronous('%s', False, 0)" % (port.name), 10)
        virtio_test.cleanup(vm, guest_worker)

    def test_lseek():
        """
        Tests the correct handling of lseek
        :note: lseek should fail
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # The virt.lseek returns PASS when the seek fails
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        guest_worker.cmd("virt.lseek('%s', 0, 0)" % (port.name), 10)
        virtio_test.cleanup(vm, guest_worker)

    def test_rw_host_offline():
        """
        Try to read from/write to host on guest when host is disconnected.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        if port.is_open():
            port.close()

        guest_worker.cmd("virt.recv('%s', 0, 1024, False)" % port.name, 10)
        match, tmp = guest_worker._cmd("virt.send('%s', 10, True)" % port.name, 10)
        if match is not None:
            test.fail(
                "Write on guest while host disconnected "
                "didn't time out.\nOutput:\n%s" % tmp
            )

        port.open()

        if len(port.sock.recv(1024)) < 10:
            test.fail("Didn't received data from guest")
        # Now the cmd("virt.send('%s'... command should be finished
        guest_worker.cmd("print('PASS: nothing')", 10)
        virtio_test.cleanup(vm, guest_worker)

    def test_rw_host_offline_big_data():
        """
        Try to read from/write to host on guest when host is disconnected
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        if port.is_open():
            port.close()

        port.clean_port()
        port.close()
        guest_worker.cmd("virt.clean_port('%s'),1024" % port.name, 10)
        match, tmp = guest_worker._cmd(
            "virt.send('%s', (1024**3)*3, True, " "is_static=True)" % port.name, 30
        )
        if match is not None:
            test.fail(
                "Write on guest while host disconnected "
                "didn't time out.\nOutput:\n%s" % tmp
            )

        time.sleep(20)

        port.open()

        rlen = 0
        while rlen < (1024**3 * 3):
            ret = select.select([port.sock], [], [], 10.0)
            if ret[0] != []:
                rlen += len(port.sock.recv((4096)))
            elif rlen != (1024**3 * 3):
                test.fail(
                    "Not all data was received," "only %d from %d" % (rlen, 1024**3 * 3)
                )
        guest_worker.cmd("print('PASS: nothing')", 10)
        virtio_test.cleanup(vm, guest_worker)

    def test_rw_blocking_mode():
        """
        Try to read/write data in blocking mode.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # Blocking mode
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        port.open()
        guest_worker.cmd("virt.blocking('%s', True)" % port.name, 10)
        # Recv should timed out
        match, tmp = guest_worker._cmd(
            "virt.recv('%s', 10, 1024, False)" % port.name, 10
        )
        if match == 0:
            test.fail("Received data even when none was sent\n" "Data:\n%s" % tmp)
        elif match is not None:
            test.fail("Unexpected fail\nMatch: %s\nData:\n%s" % (match, tmp))
        port.sock.sendall(b"1234567890")
        # Now guest received the data end escaped from the recv()
        guest_worker.cmd("print('PASS: nothing')", 10)
        virtio_test.cleanup(vm, guest_worker)

    def test_rw_nonblocking_mode():
        """
        Try to read/write data in non-blocking mode.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # Non-blocking mode
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        port.open()
        guest_worker.cmd("virt.blocking('%s', False)" % port.name, 10)
        # Recv should return FAIL with 0 received data
        match, tmp = guest_worker._cmd(
            "virt.recv('%s', 10, 1024, False)" % port.name, 10
        )
        if match == 0:
            test.fail("Received data even when none was sent\n" "Data:\n%s" % tmp)
        elif match is None:
            test.fail("Timed out, probably in blocking mode\n" "Data:\n%s" % tmp)
        elif match != 1:
            test.fail("Unexpected fail\nMatch: %s\nData:\n%s" % (match, tmp))
        port.sock.sendall(b"1234567890")
        time.sleep(0.01)
        try:
            guest_worker.cmd("virt.recv('%s', 10, 1024, False)" % port.name, 10)
        except qemu_virtio_port.VirtioPortException as details:
            if "[Errno 11] Resource temporarily unavailable" in str(details):
                # Give the VM second chance
                time.sleep(0.01)
                guest_worker.cmd("virt.recv('%s', 10, 1024, False)" % port.name, 10)
            else:
                raise details
        virtio_test.cleanup(vm, guest_worker)

    def test_basic_loopback():
        """
        Simple loop back test with loop over two ports.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        if params.get("virtio_console_params") == "serialport":
            vm, guest_worker = virtio_test.get_vm_with_worker(no_serialports=2)
            send_port, recv_port = virtio_test.get_virtio_ports(vm)[1][:2]
        else:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles=2)
            send_port, recv_port = virtio_test.get_virtio_ports(vm)[0][:2]

        data = b"Smoke test data"
        send_port.open()
        recv_port.open()
        # Set nonblocking mode
        send_port.sock.setblocking(0)
        recv_port.sock.setblocking(0)
        guest_worker.cmd(
            "virt.loopback(['%s'], ['%s'], 1024, virt.LOOP_NONE)"
            % (send_port.name, recv_port.name),
            10,
        )
        send_port.sock.sendall(data)
        tmp = b""
        i = 0
        while i <= 10:
            i += 1
            ret = select.select([recv_port.sock], [], [], 1.0)
            if ret:
                try:
                    tmp += recv_port.sock.recv(1024)
                except IOError as failure_detail:
                    test.log.warning("Got err while recv: %s", failure_detail)
            if len(tmp) >= len(data):
                break
        if tmp != data:
            test.fail("Incorrect data: '%s' != '%s'" % (data, tmp))
        guest_worker.safe_exit_loopback_threads([send_port], [recv_port])
        virtio_test.cleanup(vm, guest_worker)

    #
    # Loopback tests
    #
    @error_context.context_aware
    def test_loopback():
        """
        Virtio console loopback test.

        Creates loopback on the vm machine between send_pt and recv_pts
        ports and sends length amount of data through this connection.
        It validates the correctness of the sent data.
        :param cfg: virtio_console_params - semicolon separated loopback
                        scenarios, only $source_console_type and (multiple)
                        destination_console_types are mandatory.
                            '$source_console_type@buffer_length:
                             $destination_console_type1@$buffer_length:...:
                             $loopback_buffer_length;...'
        :param cfg: virtio_console_test_time - how long to send the data
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # PREPARE
        test_params = params["virtio_console_params"]
        test_time = int(params.get("virtio_console_test_time", 60))
        no_serialports = 0
        no_consoles = 0
        for param in test_params.split(";"):
            no_serialports = max(no_serialports, param.count("serialport"))
            no_consoles = max(no_consoles, param.count("console"))
        vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles, no_serialports)
        no_errors = 0

        (consoles, serialports) = virtio_test.get_virtio_ports(vm)

        for param in test_params.split(";"):
            if not param:
                continue
            error_context.context("test_loopback: params %s" % param, test.log.info)
            # Prepare
            param = param.split(":")
            idx_serialport = 0
            idx_console = 0
            buf_len = []
            if param[0].startswith("console"):
                send_pt = consoles[idx_console]
                idx_console += 1
            else:
                send_pt = serialports[idx_serialport]
                idx_serialport += 1
            if len(param[0].split("@")) == 2:
                buf_len.append(int(param[0].split("@")[1]))
            else:
                buf_len.append(1024)
            recv_pts = []
            for parm in param[1:]:
                if parm.isdigit():
                    buf_len.append(int(parm))
                    break  # buf_len is the last portion of param
                if parm.startswith("console"):
                    recv_pts.append(consoles[idx_console])
                    idx_console += 1
                else:
                    recv_pts.append(serialports[idx_serialport])
                    idx_serialport += 1
                if len(parm[0].split("@")) == 2:
                    buf_len.append(int(parm[0].split("@")[1]))
                else:
                    buf_len.append(1024)
            # There must be sum(idx_*) consoles + last item as loopback buf_len
            if len(buf_len) == (idx_console + idx_serialport):
                buf_len.append(1024)

            for port in recv_pts:
                port.open()

            send_pt.open()

            if len(recv_pts) == 0:
                test.fail("test_loopback: incorrect recv consoles definition")

            threads = []
            queues = []
            for i in range(0, len(recv_pts)):
                queues.append(deque())

            # Start loopback
            tmp = "'%s'" % recv_pts[0].name
            for recv_pt in recv_pts[1:]:
                tmp += ", '%s'" % (recv_pt.name)
            guest_worker.cmd(
                "virt.loopback(['%s'], [%s], %d, virt.LOOP_POLL)"
                % (send_pt.name, tmp, buf_len[-1]),
                10,
            )

            global EXIT_EVENT
            funcatexit.register(env, params.get("type"), __set_exit_event)

            # TEST
            thread = qemu_virtio_port.ThSendCheck(
                send_pt, EXIT_EVENT, queues, buf_len[0]
            )
            thread.start()
            threads.append(thread)

            for i in range(len(recv_pts)):
                thread = qemu_virtio_port.ThRecvCheck(
                    recv_pts[i], queues[i], EXIT_EVENT, buf_len[i + 1]
                )
                thread.start()
                threads.append(thread)

            err = ""
            end_time = time.time() + test_time
            no_threads = len(threads)
            transferred = [0] * no_threads
            while end_time > time.time():
                if not vm.is_alive():
                    err += "main(vmdied), "
                _transfered = []
                for i in range(no_threads):
                    if not threads[i].is_alive():
                        err += "main(th%s died), " % threads[i]
                    _transfered.append(threads[i].idx)
                if _transfered == transferred and transferred != [0] * no_threads:
                    err += "main(no_data), "
                transferred = _transfered
                if err:
                    test.log.error(
                        "Error occurred while executing loopback " "(%d out of %ds)",
                        test_time - int(end_time - time.time()),
                        test_time,
                    )
                    break
                time.sleep(1)

            EXIT_EVENT.set()
            funcatexit.unregister(env, params.get("type"), __set_exit_event)
            # TEST END
            workaround_unfinished_threads = False
            test.log.debug("Joining %s", threads[0])
            threads[0].join(5)
            if threads[0].is_alive():
                test.log.error(
                    "Send thread stuck, destroing the VM and "
                    "stopping loopback test to prevent autotest "
                    "freeze."
                )
                vm.destroy()
                break
            if threads[0].ret_code:
                err += "%s, " % threads[0]
            tmp = "%d data sent; " % threads[0].idx
            for thread in threads[1:]:
                test.log.debug("Joining %s", thread)
                thread.join(5)
                if thread.is_alive():
                    workaround_unfinished_threads = True
                    test.log.debug("Unable to destroy the thread %s", thread)
                tmp += "%d, " % thread.idx
                if thread.ret_code:
                    err += "%s, " % thread
            test.log.info("test_loopback: %s data received and verified", tmp[:-2])
            if err:
                no_errors += 1
                test.log.error(
                    "test_loopback: error occurred in threads: %s.", err[:-2]
                )

            guest_worker.safe_exit_loopback_threads([send_pt], recv_pts)

            for thread in threads:
                if thread.is_alive():
                    vm.destroy()
                    del threads[:]
                    test.error("Not all threads finished.")
            if workaround_unfinished_threads:
                test.log.debug("All threads finished at this point.")
            del threads[:]
            if not vm.is_alive():
                test.fail(
                    "VM died, can't continue the test loop. "
                    "Please check the log for details."
                )

        virtio_test.cleanup(vm, guest_worker)
        if no_errors:
            msg = (
                "test_loopback: %d errors occurred while executing test, "
                "check log for details." % no_errors
            )
            test.log.error(msg)
            test.fail(msg)

    @error_context.context_aware
    def test_interrupted_transfer():
        """
        This test creates loopback between 2 ports and interrupts transfer
        eg. by stopping the machine or by unplugging of the port.
        """

        def _replug_loop():
            """Replug ports and pci in a loop"""

            def _port_unplug(port_idx):
                dev = ports[port_idx]
                portdev = vm.devices.get_by_params({"name": dev.qemu_id})[0]
                if not portdev:
                    test.error("No port named %s" % dev.qemu_id)
                port_property = dict(
                    id=portdev.get_param("id"),
                    name=portdev.get_param("name"),
                    chardev=portdev.get_param("chardev"),
                    bus=portdev.get_param("bus"),
                    nr=portdev.get_param("nr"),
                )
                (out, ver_out) = vm.devices.simple_unplug(portdev, vm.monitor)
                if not ver_out:
                    test.error("Error occured when unplug %s" % dev.name)
                time.sleep(intr_time)
                return port_property

            def _port_plug(device, property):
                portdev = qdevices.QDevice(device)
                for key, value in {
                    "id": property["id"],
                    "chardev": property["chardev"],
                    "name": property["name"],
                    "bus": property["bus"],
                    "nr": property["nr"],
                }.items():
                    portdev.set_param(key, value)
                (out, ver_out) = vm.devices.simple_hotplug(portdev, vm.monitor)
                if not ver_out:
                    test.error("Error occured when plug port %s." % property["name"])
                time.sleep(intr_time)

            def _pci_unplug(bus):
                device = vm.devices.get_by_params({"id": str(bus).split(".")[0]})[0]
                if not device:
                    test.error("No bus %s in vm." % bus)
                bus_property = dict(id=device.get_param("id"))
                (out, ver_out) = vm.devices.simple_unplug(device, vm.monitor)
                if not ver_out:
                    test.error("Error occured when plug bus. out: %s", out)
                time.sleep(intr_time)
                return bus_property

            def _pci_plug(property):
                bus = qdevices.QDevice("virtio-serial-pci")
                bus.set_param("id", property["id"])
                (out, ver_out) = vm.devices.simple_hotplug(bus, vm.monitor)
                if not ver_out:
                    test.error("Error occured when plug bus. out: %s", out)
                time.sleep(intr_time)

            send_prop = _port_unplug(0)
            recv_prop = _port_unplug(1)
            bus_prop = _pci_unplug(send_prop["bus"])
            # replug all devices
            _pci_plug(bus_prop)
            _port_plug("virtserialport", send_prop)
            _port_plug("virtserialport", recv_prop)

        def _stop_cont():
            """Stop and resume VM"""
            vm.pause()
            time.sleep(intr_time)
            vm.resume()

        def _disconnect():
            """Disconnect and reconnect the port"""
            _guest = random.choice((tuple(), (0,), (1,), (0, 1)))
            _host = random.choice((tuple(), (0,), (1,), (0, 1)))
            if not _guest and not _host:  # Close at least one port
                _guest = (0,)
            test.log.debug("closing ports %s on host, %s on guest", _host, _guest)
            for i in _host:
                threads[i].migrate_event.clear()
                test.log.debug("Closing port %s on host", i)
                ports[i].close()
            for i in _guest:
                guest_worker.cmd("virt.close('%s')" % (ports[i].name), 10)
            time.sleep(intr_time)
            for i in _host:
                test.log.debug("Opening port %s on host", i)
                ports[i].open()
                threads[i].migrate_event.set()
            for i in _guest:
                # 50 attemps per 0.1s
                guest_worker.cmd("virt.open('%s', attempts=50)" % (ports[i].name), 10)

        def _port_replug(device, port_idx):
            """Unplug and replug port with the same name"""
            # FIXME: In Linux vport*p* are used. Those numbers are changing
            # when replugging port from pci to different pci. We should
            # either use symlinks (as in Windows) or replug with the busname
            port = ports[port_idx]
            portdev = vm.devices.get(port.qemu_id)
            if not portdev:
                test.error("No port named %s" % port.qemu_id)
            chardev = portdev.get_param("chardev")
            out, ver_out = vm.devices.simple_unplug(portdev, vm.monitor)
            if not ver_out:
                test.error(
                    "The device %s isn't hotplugged well, "
                    "result: %s" % (port.qemu_id, out)
                )
            time.sleep(intr_time)
            if not chardev:
                test.error("No chardev in guest for port %s" % port.qemu_id)
            new_portdev = qdevices.QDevice(device)
            for key, value in {
                "id": port.qemu_id,
                "chardev": chardev,
                "name": port.name,
            }.items():
                new_portdev.set_param(key, value)
            vm.devices.simple_hotplug(new_portdev, vm.monitor)

        def _serialport_send_replug():
            """hepler for executing replug of the sender port"""
            _port_replug("virtserialport", 0)

        def _console_send_replug():
            """hepler for executing replug of the sender port"""
            _port_replug("virtconsole", 0)

        def _serialport_recv_replug():
            """hepler for executing replug of the receiver port"""
            _port_replug("virtserialport", 1)

        def _console_recv_replug():
            """hepler for executing replug of the receiver port"""
            _port_replug("virtconsole", 1)

        def _serialport_random_replug():
            """hepler for executing replug of random port"""
            _port_replug("virtserialport", random.choice((0, 1)))

        def _console_random_replug():
            """hepler for executing replug of random port"""
            _port_replug("virtconsole", random.choice((0, 1)))

        def _s3():
            """
            Suspend to mem (S3) and resume the VM.
            """
            session.sendline(set_s3_cmd)  # pylint: disable=E0606
            time.sleep(intr_time)
            if not vm.monitor.verify_status("suspended"):
                test.log.debug("VM not yet suspended, periodic check started.")
                while not vm.monitor.verify_status("suspended"):
                    pass
            vm.monitor.cmd("system_wakeup")

        def _s4():
            """
            Hibernate (S4) and resume the VM.
            :note: data loss is handled differently in this case. First we
                   set data loss to (almost) infinity. After the resume we
                   periodically check the number of transferred and lost data.
                   When there is no loss and number of transferred data is
                   sufficient, we take it as the initial data loss is over.
                   Than we set the allowed loss to 0.
            """
            set_s4_cmd = params["set_s4_cmd"]
            _loss = threads[1].sendidx
            _count = threads[1].idx
            # Prepare, hibernate and wake the machine
            threads[0].migrate_event.clear()
            threads[1].migrate_event.clear()
            oldport = vm.virtio_ports[0]
            portslen = len(vm.virtio_ports)
            vm.wait_for_login().sendline(set_s4_cmd)
            suspend_timeout = 240 + int(params.get("smp", 1)) * 60
            if not utils_misc.wait_for(vm.is_dead, suspend_timeout, 2, 2):
                test.fail("VM refuses to go down. Suspend failed.")
            time.sleep(intr_time)
            vm.create()
            for _ in range(10):  # Wait until new ports are created
                try:
                    if (
                        vm.virtio_ports[0] != oldport
                        and len(vm.virtio_ports) == portslen
                    ):
                        break
                except IndexError:
                    pass
                time.sleep(1)
            else:
                test.fail(
                    "New virtio_ports were not created with"
                    "the new VM or the VM failed to start."
                )
            if is_serialport:
                ports = virtio_test.get_virtio_ports(vm)[1]
            else:
                ports = virtio_test.get_virtio_ports(vm)[0]
            threads[0].port = ports[0]
            threads[1].port = ports[1]
            threads[0].migrate_event.set()  # Wake up sender thread immediately
            threads[1].migrate_event.set()
            guest_worker.reconnect(vm, 360)
            test.log.debug("S4: watch 1s for initial data loss stabilization.")
            for _ in range(10):
                time.sleep(0.1)
                loss = threads[1].sendidx
                count = threads[1].idx
                dloss = _loss - loss
                dcount = count - _count
                test.log.debug("loss=%s, verified=%s", dloss, dcount)
                if dcount < 100:
                    continue
                if dloss == 0:
                    # at least 100 chars were transferred without data loss
                    # the initial loss is over
                    break
                _loss = loss
                _count = count
            else:
                test.fail(
                    "Initial data loss is not over after 1s "
                    "or no new data were received."
                )
            # now no loss is allowed
            threads[1].sendidx = 0
            # DEBUG: When using ThRecv debug, you must wake-up the recv thread
            # here (it waits only 1s for new data
            # threads[1].migrate_event.set()

        error_context.context("Preparing loopback", test.log.info)
        test_time = float(params.get("virtio_console_test_time", 10))
        intr_time = float(params.get("virtio_console_intr_time", 0))
        no_repeats = int(params.get("virtio_console_no_repeats", 1))
        interruption = params["virtio_console_interruption"]
        is_serialport = params.get("virtio_console_params") == "serialport"
        buflen = int(params.get("virtio_console_buflen", 1))
        if is_serialport:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_serialports=2)
            (_, ports) = virtio_test.get_virtio_ports(vm)
        else:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles=2)
            (ports, _) = virtio_test.get_virtio_ports(vm)

        # Set the interruption function and related variables
        send_resume_ev = None
        recv_resume_ev = None
        acceptable_loss = 0
        if interruption == "stop":
            interruption = _stop_cont
        elif interruption == "disconnect":
            interruption = _disconnect
            acceptable_loss = 100000
            send_resume_ev = threading.Event()
            recv_resume_ev = threading.Event()
        elif interruption == "replug_send":
            if is_serialport:
                interruption = _serialport_send_replug
            else:
                interruption = _console_send_replug
            acceptable_loss = max(buflen * 10, 1000)
        elif interruption == "replug_recv":
            if is_serialport:
                interruption = _serialport_recv_replug
            else:
                interruption = _console_recv_replug
            acceptable_loss = max(buflen * 5, 1000)
        elif interruption == "replug_random":
            if is_serialport:
                interruption = _serialport_random_replug
            else:
                interruption = _console_random_replug
            acceptable_loss = max(buflen * 10, 1000)
        elif interruption == "replug_loop":
            if is_serialport:
                interruption = _replug_loop
            acceptable_loss = max(buflen * 15, 1000)
        elif interruption == "s3":
            interruption = _s3
            acceptable_loss = 2000
            session = vm.wait_for_login()
            set_s3_cmd = params["set_s3_cmd"]
            if session.cmd_status(params["check_s3_support_cmd"]):
                test.cancel("Suspend to mem (S3) not supported.")
        elif interruption == "s4":
            interruption = _s4
            session = vm.wait_for_login()
            if session.cmd_status(params["check_s4_support_cmd"]):
                test.cancel("Suspend to disk (S4) not supported.")
            acceptable_loss = 99999999  # loss is set in S4 rutine
            send_resume_ev = threading.Event()
            recv_resume_ev = threading.Event()
        else:
            test.cancel(
                "virtio_console_interruption = '%s' " "is unknown." % interruption
            )

        send_pt = ports[0]
        recv_pt = ports[1]

        recv_pt.open()
        send_pt.open()

        threads = []
        queues = [deque()]

        # Start loopback
        error_context.context("Starting loopback", test.log.info)
        err = ""
        # TODO: Use normal LOOP_NONE when bz796048 is resolved.
        guest_worker.cmd(
            "virt.loopback(['%s'], ['%s'], %s, virt.LOOP_"
            "RECONNECT_NONE)" % (send_pt.name, recv_pt.name, buflen),
            10,
        )

        funcatexit.register(env, params.get("type"), __set_exit_event)

        threads.append(
            qemu_virtio_port.ThSendCheck(
                send_pt, EXIT_EVENT, queues, buflen, send_resume_ev
            )
        )
        threads[-1].start()
        _ = params.get("virtio_console_debug")
        threads.append(
            qemu_virtio_port.ThRecvCheck(
                recv_pt,
                queues[0],
                EXIT_EVENT,
                buflen,
                acceptable_loss,
                recv_resume_ev,
                debug=_,
            )
        )
        threads[-1].start()

        test.log.info(
            "Starting the loop 2+%d*(%d+%d+intr_overhead)+2 >= %ss",
            no_repeats,
            intr_time,
            test_time,
            (4 + no_repeats * (intr_time + test_time)),
        )
        # Lets transfer some data before the interruption
        time.sleep(2)
        if not threads[0].is_alive():
            test.fail("Sender thread died before interruption.")
        if not threads[0].is_alive():
            test.fail("Receiver thread died before interruption.")

        # 0s interruption without any measurements
        if params.get("virtio_console_micro_repeats"):
            error_context.context("Micro interruptions", test.log.info)
            threads[1].sendidx = acceptable_loss
            for i in range(int(params.get("virtio_console_micro_repeats"))):
                interruption()

        error_context.context("Normal interruptions", test.log.info)
        try:
            for i in range(no_repeats):
                error_context.context("Interruption nr. %s" % i)
                threads[1].sendidx = acceptable_loss
                interruption()
                count = threads[1].idx
                test.log.debug("Transfered data: %s", count)
                # Be friendly to very short test_time values
                for _ in range(10):
                    time.sleep(test_time)
                    test.log.debug("Transfered data2: %s", threads[1].idx)
                    if count == threads[1].idx and threads[1].is_alive():
                        test.log.warning(
                            "No data received after %ds, extending " "test_time",
                            test_time,
                        )
                    else:
                        break
                threads[1].reload_loss_idx()
                if count == threads[1].idx or not threads[1].is_alive():
                    if not threads[1].is_alive():
                        test.log.error("RecvCheck thread stopped unexpectedly.")
                    if count == threads[1].idx:
                        test.log.error("No data transferred after interruption!")
                    test.log.info(
                        "Output from GuestWorker:\n%s", guest_worker.read_nonblocking()
                    )
                    try:
                        session = vm.login()
                        data = session.cmd_output("dmesg")
                        if "WARNING:" in data:
                            test.log.warning("There are warnings in dmesg:\n%s", data)
                    except Exception as inst:
                        test.log.warning("Can't verify dmesg: %s", inst)
                    try:
                        vm.monitor.info("qtree")
                    except Exception as inst:
                        test.log.warning("Failed to get info from qtree: %s", inst)
                    EXIT_EVENT.set()
                    vm.verify_kernel_crash()
                    test.fail("No data transferred after interruption.")
        except Exception as inst:
            err = "main thread, "
            test.log.error("interrupted_loopback failed with exception: %s", inst)

        error_context.context("Stopping loopback", test.log.info)
        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get("type"), __set_exit_event)
        workaround_unfinished_threads = False
        threads[0].join(5)
        if threads[0].is_alive():
            workaround_unfinished_threads = True
            test.log.error(
                "Send thread stuck, destroing the VM and "
                "stopping loopback test to prevent autotest freeze."
            )
            vm.destroy()
        for thread in threads[1:]:
            test.log.debug("Joining %s", thread)
            thread.join(5)
            if thread.is_alive():
                workaround_unfinished_threads = True
                test.log.debug("Unable to destroy the thread %s", thread)
        if not err:  # Show only on success
            test.log.info(
                "%d data sent; %d data received and verified; %d "
                "interruptions %ds each.",
                threads[0].idx,
                threads[1].idx,
                no_repeats,
                test_time,
            )
        if threads[0].ret_code:
            err += "sender, "
        if threads[1].ret_code:
            err += "receiver, "

        # Ports might change (in suspend S4)
        if is_serialport:
            (send_pt, recv_pt) = virtio_test.get_virtio_ports(vm)[1][:2]
        else:
            (send_pt, recv_pt) = virtio_test.get_virtio_ports(vm)[0][:2]

        # VM might be recreated se we have to reconnect.
        guest_worker.safe_exit_loopback_threads([send_pt], [recv_pt])

        for thread in threads:
            if thread.is_alive():
                vm.destroy()
                del threads[:]
                test.error("Not all threads finished.")
        if workaround_unfinished_threads:
            test.log.debug("All threads finished at this point.")

        del threads[:]

        virtio_test.cleanup(env.get_vm(params["main_vm"]), guest_worker)

        if err:
            test.fail("%s failed" % err[:-2])

    def _process_stats(stats, scale=1.0):
        """
        Process the stats to human readable form.
        :param stats: List of measured data.
        """
        if not stats:
            return None
        for i in range((len(stats) - 1), 0, -1):
            stats[i] = stats[i] - stats[i - 1]
            stats[i] /= scale
        stats[0] /= scale
        stats = sorted(stats)
        return stats

    @error_context.context_aware
    def test_perf():
        """
        Tests performance of the virtio_console tunnel. First it sends the data
        from host to guest and than back. It provides informations about
        computer utilization and statistic informations about the throughput.

        :param cfg: virtio_console_params - semicolon separated scenarios:
                        '$console_type@$buffer_length:$test_duration;...'
        :param cfg: virtio_console_test_time - default test_duration time
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        from autotest.client import utils

        test_params = params["virtio_console_params"]
        test_time = int(params.get("virtio_console_test_time", 60))
        no_serialports = 0
        no_consoles = 0
        if test_params.count("serialport"):
            no_serialports = 1
        if test_params.count("serialport"):
            no_consoles = 1
        vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles, no_serialports)
        (consoles, serialports) = virtio_test.get_virtio_ports(vm)
        consoles = [consoles, serialports]
        no_errors = 0

        for param in test_params.split(";"):
            if not param:
                continue
            error_context.context("test_perf: params %s" % param, test.log.info)
            EXIT_EVENT.clear()
            # Prepare
            param = param.split(":")
            duration = test_time
            if len(param) > 1:
                try:
                    duration = float(param[1])
                except ValueError:
                    pass
            param = param[0].split("@")
            if len(param) > 1 and param[1].isdigit():
                buf_len = int(param[1])
            else:
                buf_len = 1024
            param = param[0] == "serialport"
            port = consoles[param][0]

            port.open()

            data = b""
            for _ in range(buf_len):
                data += b"%c" % random.randrange(255)

            funcatexit.register(env, params.get("type"), __set_exit_event)

            time_slice = float(duration) / 100

            # HOST -> GUEST
            guest_worker.cmd(
                'virt.loopback(["%s"], [], %d, virt.LOOP_NONE)' % (port.name, buf_len),
                10,
            )
            thread = qemu_virtio_port.ThSend(port.sock, data, EXIT_EVENT)
            stats = array.array("f", [])
            loads = utils.SystemLoad(
                [(os.getpid(), "autotest"), (vm.get_pid(), "VM"), 0]
            )
            try:
                loads.start()
                _time = time.time()
                thread.start()
                for _ in range(100):
                    stats.append(thread.idx)
                    time.sleep(time_slice)
                _time = time.time() - _time - duration
                test.log.info(loads.get_cpu_status_string()[:-1])
                test.log.info(loads.get_mem_status_string()[:-1])
                EXIT_EVENT.set()
                thread.join()
                if thread.ret_code:
                    no_errors += 1
                    test.log.error(
                        "test_perf: error occurred in thread %s " "(H2G)", thread
                    )
                elif thread.idx == 0:
                    no_errors += 1
                    test.log.error("test_perf: no data sent (H2G)")

                # Let the guest read-out all the remaining data
                for _ in range(60):
                    if guest_worker._cmd(
                        "virt.poll('%s', %s)" % (port.name, select.POLLIN), 10
                    )[0]:
                        break
                    time.sleep(1)
                else:
                    test.fail("Unable to read-out all remaining " "data in 60s.")

                guest_worker.safe_exit_loopback_threads([port], [])

                if _time > time_slice:
                    test.log.error(
                        "Test ran %fs longer which is more than one " "time slice",
                        _time,
                    )
                else:
                    test.log.debug("Test ran %fs longer", _time)
                stats = _process_stats(stats[1:], time_slice * 1048576)
                test.log.debug("Stats = %s", stats)
                test.log.info(
                    "Host -> Guest [MB/s] (min/med/max) = %.3f/%.3f/" "%.3f",
                    stats[0],
                    stats[len(stats) / 2],
                    stats[-1],
                )

                del thread

                # GUEST -> HOST
                EXIT_EVENT.clear()
                stats = array.array("f", [])
                guest_worker.cmd(
                    "virt.send_loop_init('%s', %d)" % (port.name, buf_len), 30
                )
                thread = qemu_virtio_port.ThRecv(port.sock, EXIT_EVENT, buf_len)
                thread.start()
                loads.start()
                guest_worker.cmd("virt.send_loop()", 10)
                _time = time.time()
                for _ in range(100):
                    stats.append(thread.idx)
                    time.sleep(time_slice)
                _time = time.time() - _time - duration
                test.log.info(loads.get_cpu_status_string()[:-1])
                test.log.info(loads.get_mem_status_string()[:-1])
                guest_worker.cmd("virt.exit_threads()", 10)
                EXIT_EVENT.set()
                thread.join()
                if thread.ret_code:
                    no_errors += 1
                    test.log.error(
                        "test_perf: error occurred in thread %s" "(G2H)", thread
                    )
                elif thread.idx == 0:
                    no_errors += 1
                    test.log.error("test_perf: No data received (G2H)")
                # Deviation is higher than single time_slice
                if _time > time_slice:
                    test.log.error(
                        "Test ran %fs longer which is more than one " "time slice",
                        _time,
                    )
                else:
                    test.log.debug("Test ran %fs longer", _time)
                stats = _process_stats(stats[1:], time_slice * 1048576)
                test.log.debug("Stats = %s", stats)
                test.log.info(
                    "Guest -> Host [MB/s] (min/med/max) = %.3f/%.3f/" "%.3f",
                    stats[0],
                    stats[len(stats) / 2],
                    stats[-1],
                )
            except Exception as inst:
                test.log.error(
                    "test_perf: Failed with %s, starting virtio_test.cleanup", inst
                )
                loads.stop()
                try:
                    guest_worker.cmd("virt.exit_threads()", 10)
                    EXIT_EVENT.set()
                    thread.join()
                    raise inst
                except Exception as inst:
                    test.log.error("test_perf: Critical failure, killing VM %s", inst)
                    EXIT_EVENT.set()
                    vm.destroy()
                    del thread
                    raise inst
            funcatexit.unregister(env, params.get("type"), __set_exit_event)
        virtio_test.cleanup(vm, guest_worker)
        if no_errors:
            msg = (
                "test_perf: %d errors occurred while executing test, "
                "check log for details." % no_errors
            )
            test.log.error(msg)
            test.fail(msg)

    #
    # Migration tests
    #
    @error_context.context_aware
    def _tmigrate(use_serialport, no_ports, no_migrations, blocklen, offline):
        """
        An actual migration test. It creates loopback on guest from first port
        to all remaining ports. Than it sends and validates the data.
        During this it tries to migrate the vm n-times.

        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param consoles: Field of virtio ports with the minimum of 2 items.
        :param parms: [media, no_migration, send-, recv-, loopback-buffer_len]
        """
        # PREPARE
        if use_serialport:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_serialports=no_ports)
            ports = virtio_test.get_virtio_ports(vm)[1]
        else:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles=no_ports)
            ports = virtio_test.get_virtio_ports(vm)[0]

        # TODO BUG: sendlen = max allowed data to be lost per one migration
        # TODO BUG: using SMP the data loss is up to 4 buffers
        # 2048 = char.dev. socket size, parms[2] = host->guest send buffer size
        sendlen = 2 * 2 * max(qemu_virtio_port.SOCKET_SIZE, blocklen)
        if not offline:  # TODO BUG: online migration causes more loses
            # TODO: Online migration lose n*buffer. n depends on the console
            # troughput. FIX or analyse it's cause.
            sendlen = 1000 * sendlen
        for port in ports[1:]:
            port.open()

        ports[0].open()

        threads = []
        queues = []
        verified = []
        for i in range(0, len(ports[1:])):
            queues.append(deque())
            verified.append(0)

        tmp = "'%s'" % ports[1:][0].name
        for recv_pt in ports[1:][1:]:
            tmp += ", '%s'" % (recv_pt.name)
        guest_worker.cmd(
            "virt.loopback(['%s'], [%s], %d, virt.LOOP_POLL)"
            % (ports[0].name, tmp, blocklen),
            10,
        )

        funcatexit.register(env, params.get("type"), __set_exit_event)

        # TEST
        thread = qemu_virtio_port.ThSendCheck(
            ports[0], EXIT_EVENT, queues, blocklen, migrate_event=threading.Event()
        )
        thread.start()
        threads.append(thread)

        for i in range(len(ports[1:])):
            _ = threading.Event()
            thread = qemu_virtio_port.ThRecvCheck(
                ports[1:][i],
                queues[i],
                EXIT_EVENT,
                blocklen,
                sendlen=sendlen,
                migrate_event=_,
            )
            thread.start()
            threads.append(thread)

        i = 0
        while i < 6:
            tmp = "%d data sent; " % threads[0].idx
            for thread in threads[1:]:
                tmp += "%d, " % thread.idx
            test.log.debug("test_migrate: %s data received and verified", tmp[:-2])
            i += 1
            time.sleep(2)

        for j in range(no_migrations):
            error_context.context(
                "Performing migration number %s/%s" % (j, no_migrations)
            )
            vm = migration.migrate(vm, env, 3600, "exec", 0, offline)
            if not vm:
                test.fail("Migration failed")

            # Set new ports to Sender and Recver threads
            # TODO: get ports in this function and use the right ports...
            if use_serialport:
                ports = virtio_test.get_virtio_ports(vm)[1]
            else:
                ports = virtio_test.get_virtio_ports(vm)[0]
            for i in range(len(threads)):
                threads[i].port = ports[i]
                threads[i].migrate_event.set()

            # OS is sometime a bit dizzy. DL=30
            # guest_worker.reconnect(vm, timeout=30)

            i = 0
            while i < 6:
                tmp = "%d data sent; " % threads[0].idx
                for thread in threads[1:]:
                    tmp += "%d, " % thread.idx
                test.log.debug("test_migrate: %s data received and verified", tmp[:-2])
                i += 1
                time.sleep(2)
            if not threads[0].is_alive():
                if EXIT_EVENT.is_set():
                    test.fail(
                        "Exit event emitted, check the log "
                        "for send/recv thread failure."
                    )
                else:
                    EXIT_EVENT.set()
                    test.fail(
                        "Send thread died unexpectedly in " "migration %d" % (j + 1)
                    )
            for i in range(0, len(ports[1:])):
                if not threads[i + 1].is_alive():
                    EXIT_EVENT.set()
                    test.fail(
                        "Recv thread %d died unexpectedly in "
                        "migration %d" % (i, (j + 1))
                    )
                if verified[i] == threads[i + 1].idx:
                    EXIT_EVENT.set()
                    test.fail(
                        "No new data in %d console were "
                        "transferred after migration %d" % (i, (j + 1))
                    )
                verified[i] = threads[i + 1].idx
            test.log.info("%d out of %d migration(s) passed", (j + 1), no_migrations)
            # If we get to this point let's assume all threads were reconnected
            for thread in threads:
                thread.migrate_event.clear()
            # TODO detect recv-thread failure and throw out whole test

        # FINISH
        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get("type"), __set_exit_event)
        # Send thread might fail to exit when the guest stucks
        workaround_unfinished_threads = False
        threads[0].join(5)
        if threads[0].is_alive():
            workaround_unfinished_threads = True
            test.log.error(
                "Send thread stuck, destroing the VM and "
                "stopping loopback test to prevent autotest freeze."
            )
            vm.destroy()
        tmp = "%d data sent; " % threads[0].idx
        err = ""

        for thread in threads[1:]:
            thread.join(5)
            if thread.is_alive():
                workaround_unfinished_threads = True
                test.log.debug("Unable to destroy the thread %s", thread)
            tmp += "%d, " % thread.idx
            if thread.ret_code:
                err += "%s, " % thread
        test.log.info(
            "test_migrate: %s data received and verified during %d " "migrations",
            tmp[:-2],
            no_migrations,
        )
        if err:
            msg = "test_migrate: error occurred in threads: %s." % err[:-2]
            test.log.error(msg)
            test.fail(msg)

        # CLEANUP
        guest_worker.reconnect(vm)
        guest_worker.safe_exit_loopback_threads([ports[0]], ports[1:])

        for thread in threads:
            if thread.is_alive():
                vm.destroy()
                del threads[:]
                test.error("Not all threads finished.")
        if workaround_unfinished_threads:
            test.log.debug("All threads finished at this point.")
        del threads[:]
        virtio_test.cleanup(vm, guest_worker)

    def _test_migrate(offline):
        """
        Migration test wrapper, see the actual test_migrate_* tests for details
        """
        no_migrations = int(params.get("virtio_console_no_migrations", 5))
        no_ports = int(params.get("virtio_console_no_ports", 2))
        blocklen = int(params.get("virtio_console_blocklen", 1024))
        use_serialport = params.get("virtio_console_params") == "serialport"
        _tmigrate(use_serialport, no_ports, no_migrations, blocklen, offline)

    def test_migrate_offline():
        """
        Tests whether the virtio-{console,port} are able to survive the offline
        migration.
        :param cfg: virtio_console_no_migrations - how many times to migrate
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_blocklen - send/recv block length
        :param cfg: virtio_console_no_ports - minimum number of loopback ports
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        _test_migrate(offline=True)

    def test_migrate_online():
        """
        Tests whether the virtio-{console,port} are able to survive the online
        migration.
        :param cfg: virtio_console_no_migrations - how many times to migrate
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_blocklen - send/recv block length
        :param cfg: virtio_console_no_ports - minimum number of loopback ports
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        _test_migrate(offline=False)

    def _virtio_dev_add(vm, pci_id, port_id, console="no"):
        """
        Adds virtio serialport device.
        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param pci_id: Id of virtio-serial-pci device.
        :param port_id: Id of port.
        :param console: if "yes" inicialize console.
        """
        port = "serialport-"
        port_type = "virtserialport"
        if console == "yes":
            port = "console-"
            port_type = "virtconsole"
        port += "%d-%d" % (pci_id, port_id)
        new_portdev = qdevices.QDevice(port_type)
        for key, value in {
            "id": port,
            "name": port,
            "bus": "virtio_serial_pci" "%d.0" % pci_id,
        }.items():
            new_portdev.set_param(key, value)
        (result, ver_out) = vm.devices.simple_hotplug(new_portdev, vm.monitor)

        if console == "no":
            vm.virtio_ports.append(qemu_virtio_port.VirtioSerial(port, port, None))
        else:
            vm.virtio_ports.append(qemu_virtio_port.VirtioConsole(port, port, None))
        if not ver_out:
            test.error(
                "The virtioserialport isn't hotplugged well, result: %s" % result
            )

    def _virtio_dev_del(vm, pci_id, port_id):
        """
        Removes virtio serialport device.
        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param pci_id: Id of virtio-serial-pci device.
        :param port_id: Id of port.
        """
        for port in vm.virtio_ports:
            if port.name.endswith("-%d-%d" % (pci_id, port_id)):
                portdev = vm.devices.get_by_params({"name": port.qemu_id})[0]
                (result, ver_out) = vm.devices.simple_unplug(portdev, vm.monitor)
                vm.virtio_ports.remove(port)
                if not ver_out:
                    test.error(
                        "The virtioserialport isn't hotunplugged well, "
                        "result: %s" % result
                    )
                return
        test.fail(
            "Removing port which is not in vm.virtio_ports"
            " ...-%d-%d" % (pci_id, port_id)
        )

    def test_hotplug():
        """
        Check the hotplug/unplug of virtio-consoles ports.
        TODO: co vsechno to opravdu testuje?
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_pause - pause between monitor commands
        """
        # TODO: Support the new port name_prefix
        # TODO: 101 of 100 ports are initialised (might be related to above^^)

        # TODO: Rewrite this test. It was left as it was before the virtio_port
        # conversion and looked too messy to repair it during conversion.
        # TODO: Split this test into multiple variants
        # TODO: Think about customizable params
        # TODO: use qtree to detect the right virtio-serial-pci name
        # TODO: QMP
        if params.get("virtio_console_params") == "serialport":
            console = "no"
        else:
            console = "yes"
        pause = int(params.get("virtio_console_pause", 1))
        test.log.info("Timeout between hotplug operations t=%fs", pause)

        vm = virtio_test.get_vm_with_ports(0, 2, spread=0, quiet=True, strict=True)
        consoles = virtio_test.get_virtio_ports(vm)
        # send/recv might block for ever, set non-blocking mode
        consoles[1][0].open()
        consoles[1][1].open()
        consoles[1][0].sock.setblocking(0)
        consoles[1][1].sock.setblocking(0)
        test.log.info("Test correct initialization of hotplug ports")
        for bus_id in range(1, 5):  # count of pci device
            new_pcidev = qdevices.QDevice(get_virtio_serial_name())
            new_pcidev.set_param("id", "virtio_serial_pci%d" % bus_id)
            (result, ver_out) = vm.devices.simple_hotplug(new_pcidev, vm.monitor)
            if not ver_out:
                test.error(
                    "The virtio serial pci isn't hotplugged well, log: %s" % result
                )
            for i in range(bus_id * 5 + 5):  # max ports 30
                _virtio_dev_add(vm, bus_id, i, console)
                time.sleep(pause)
        # Test correct initialization of hotplug ports
        time.sleep(10)  # Timeout for port initialization
        guest_worker = qemu_virtio_port.GuestWorker(vm)

        test.log.info("Delete ports during ports in use")
        # Delete ports when ports are used.
        guest_worker.cmd(
            "virt.loopback(['%s'], ['%s'], 1024,"
            "virt.LOOP_POLL)" % (consoles[1][0].name, consoles[1][1].name),
            10,
        )
        funcatexit.register(env, params.get("type"), __set_exit_event)

        send = qemu_virtio_port.ThSend(
            consoles[1][0].sock, "Data", EXIT_EVENT, quiet=True
        )
        recv = qemu_virtio_port.ThRecv(consoles[1][1].sock, EXIT_EVENT, quiet=True)
        send.start()
        time.sleep(2)
        recv.start()

        # Try to delete ports under load
        portdev = vm.devices.get_by_params({"name": consoles[1][1].qemu_id})[0]
        (result, ver_out) = vm.devices.simple_unplug(portdev, vm.monitor)
        portdev_ = vm.devices.get_by_params({"name": consoles[1][0].qemu_id})[0]
        (result_, ver_out_) = vm.devices.simple_unplug(portdev_, vm.monitor)
        vm.virtio_ports = vm.virtio_ports[2:]
        if not (ver_out and ver_out_):
            test.error(
                "The ports aren't hotunplugged well, log: %s\n, %s" % (result, result_)
            )

        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get("type"), __set_exit_event)
        send.join()
        recv.join()
        guest_worker.cmd("virt.exit_threads()", 10)
        guest_worker.cmd("guest_exit()", 10)

        test.log.info("Trying to add maximum count of ports to one pci device")
        # Try to add ports
        for i in range(30):  # max port 30
            _virtio_dev_add(vm, 0, i, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd("guest_exit()", 10)

        test.log.info("Trying delete and add again part of ports")
        # Try to delete ports
        for i in range(25):  # max port 30
            _virtio_dev_del(vm, 0, i)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd("guest_exit()", 10)

        # Try to add ports
        for i in range(5):  # max port 30
            _virtio_dev_add(vm, 0, i, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd("guest_exit()", 10)

        test.log.info("Trying to add and delete one port 100 times")
        # Try 100 times add and delete one port.
        for i in range(100):
            _virtio_dev_del(vm, 0, 0)
            time.sleep(pause)
            _virtio_dev_add(vm, 0, 0, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        virtio_test.cleanup(guest_worker=guest_worker)
        # VM is broken (params mismatches actual state)
        vm.destroy()

    @error_context.context_aware
    def test_hotplug_virtio_pci():
        """
        Tests hotplug/unplug of the virtio-serial-pci bus.
        :param cfg: virtio_console_pause - pause between monitor commands
        :param cfg: virtio_console_loops - how many loops to run
        """
        # TODO: QMP
        # TODO: check qtree for device presence
        pause = float(params.get("virtio_console_pause", 1))
        vm = virtio_test.get_vm_with_ports()
        idx = len(virtio_test.get_virtio_ports(vm)[0])
        error_context.context("Hotplug while booting", test.log.info)
        vio_type = get_virtio_serial_name()
        if "pci" in vio_type:
            vio_parent_bus = {"aobject": "pci.0"}
        else:
            vio_parent_bus = None
        vm.wait_for_login()
        for i in range(int(params.get("virtio_console_loops", 10))):
            error_context.context(
                "Hotpluging virtio_pci (iteration %d)" % i, test.log.info
            )
            new_dev = qdevices.QDevice(
                vio_type, {"id": "virtio_serial_pci%d" % idx}, parent_bus=vio_parent_bus
            )

            # Hotplug
            out, ver_out = vm.devices.simple_hotplug(new_dev, vm.monitor)
            if not ver_out:
                test.error(
                    "The device %s isn't hotplugged well, "
                    "result: %s" % (new_dev.aid, out)
                )
            time.sleep(pause)
            # Unplug
            out, ver_out = vm.devices.simple_unplug(new_dev, vm.monitor)
            if ver_out is False:
                test.fail("Device not unplugged. Iteration: %s, result: %s" % (i, out))

    #
    # Destructive tests
    #
    def test_rw_notconnect_guest():
        """
        Try to send to/read from guest on host while guest not recvs/sends any
        data.
        """
        use_serialport = params.get("virtio_console_params") == "serialport"
        if use_serialport:
            vm = virtio_test.get_vm_with_ports(no_serialports=1, strict=True)
        else:
            vm = virtio_test.get_vm_with_ports(no_consoles=1, strict=True)
        if use_serialport:
            port = virtio_test.get_virtio_ports(vm)[1][0]
        else:
            port = virtio_test.get_virtio_ports(vm)[0][0]
        if not port.is_open():
            port.open()
        else:
            port.close()
            port.open()

        port.sock.settimeout(20.0)
        try:
            try:
                sent1 = 0
                for _ in range(1000000):
                    sent1 += port.sock.send(b"a")
            except socket.timeout:
                test.log.info("Data sending to closed port timed out.")

            test.log.info("Bytes sent to client: %d", sent1)
            test.log.info("Open and then close port %s", port.name)
            guest_worker = qemu_virtio_port.GuestWorker(vm)
            # Test of live and open and close port again
            guest_worker.cleanup()
            port.sock.settimeout(20.0)
            try:
                sent2 = 0
                for _ in range(40000):
                    sent2 = port.sock.send(b"a")
            except socket.timeout:
                test.log.info("Data sending to closed port timed out.")

            test.log.info("Bytes sent to client: %d", sent2)
        except Exception as inst:
            test.log.error("test_rw_notconnect_guest failed: %s", inst)
            port.sock.settimeout(None)
            guest_worker = qemu_virtio_port.GuestWorker(vm)
            virtio_test.cleanup(vm, guest_worker)
            raise inst
        if sent1 != sent2:
            test.log.warning(
                "Inconsistent behavior: First sent %d bytes and "
                "second sent %d bytes",
                sent1,
                sent2,
            )

        port.sock.settimeout(None)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        virtio_test.cleanup(vm, guest_worker)

    def test_rmmod():
        """
        Remove and load virtio_console kernel module.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = virtio_test.get_vm_with_single_port(
            params.get("virtio_console_params")
        )
        guest_worker.cleanup()
        session = vm.wait_for_login()
        if session.cmd_status("lsmod | grep virtio_console"):
            test.cancel(
                "virtio_console not loaded, probably "
                " not compiled as module. Can't test it."
            )
        session.cmd("rmmod -f virtio_console")
        session.cmd("modprobe virtio_console")
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd("virt.clean_port('%s'),1024" % port.name, 2)
        virtio_test.cleanup(vm, guest_worker)

    def test_max_ports():
        """
        Try to start and initialize machine with maximum supported number of
        virtio ports. (30)
        :param cfg: virtio_console_params - which type of virtio port to test
        """
        port_count = 30
        if params.get("virtio_console_params") == "serialport":
            test.log.debug("Count of serialports: %d", port_count)
            vm = virtio_test.get_vm_with_ports(0, port_count, quiet=True)
        else:
            test.log.debug("Count of consoles: %d", port_count)
            vm = virtio_test.get_vm_with_ports(port_count, 0, quiet=True)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        virtio_test.cleanup(vm, guest_worker)

    def test_max_serials_and_consoles():
        """
        Try to start and initialize machine with maximum supported number of
        virtio ports with 15 virtconsoles and 15 virtserialports.
        """
        port_count = 15
        test.log.debug("Count of virtports: %d %d", port_count, port_count)
        vm = virtio_test.get_vm_with_ports(port_count, port_count, quiet=True)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        virtio_test.cleanup(vm, guest_worker)

    def test_stressed_restart():
        """
        Try to gently shutdown the machine while sending data through virtio
        port.
        :note: VM should shutdown safely.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        :param cfg: virtio_console_method - reboot method (shell, system_reset)
        """
        if params.get("virtio_console_params") == "serialport":
            vm, guest_worker = virtio_test.get_vm_with_worker(no_serialports=1)
            _ports, ports = virtio_test.get_virtio_ports(vm)
        else:
            vm, guest_worker = virtio_test.get_vm_with_worker(no_consoles=1)
            ports, _ports = virtio_test.get_virtio_ports(vm)
        ports.extend(_ports)

        session = vm.wait_for_login()
        for port in ports:
            port.open()
        # If more than one, send data on the other ports
        process = []
        for port in ports[1:]:
            guest_worker.cmd("virt.close('%s')" % (port.name), 2)
            guest_worker.cmd("virt.open('%s')" % (port.name), 2)
            try:
                process.append(
                    Popen(
                        "dd if=/dev/random of='%s' bs=4096 " "&>/dev/null &" % port.path
                    )
                )
            except Exception:
                pass
        # Start sending data, it won't finish anyway...
        guest_worker._cmd(
            "virt.send('%s', 1024**3, True, is_static=True)" % ports[0].name, 1
        )
        # Let the computer transfer some bytes :-)
        time.sleep(2)

        # Power off the computer
        try:
            vm.reboot(
                session=session,
                method=params.get("virtio_console_method", "shell"),
                timeout=720,
            )
        except Exception as details:
            for process in process:
                process.terminate()
            for port in vm.virtio_ports:
                port.close()
            test.fail("Fail to reboot VM:\n%s" % details)

        # close the virtio ports and process
        for process in process:
            process.terminate()
        for port in vm.virtio_ports:
            port.close()
        error_context.context("Executing basic loopback after reboot.", test.log.info)
        test_basic_loopback()

    @error_context.context_aware
    def test_unplugged_restart():
        """
        Try to unplug all virtio ports and gently restart machine
        :note: VM should shutdown safely.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        :param cfg: virtio_console_method - reboot method (shell, system_reset)
        """
        if params.get("virtio_console_params") == "serialport":
            vm = virtio_test.get_vm_with_ports(no_serialports=1)
        else:
            vm = virtio_test.get_vm_with_ports(no_consoles=1)
        ports, _ports = virtio_test.get_virtio_ports(vm)
        ports.extend(_ports)

        # Remove all ports:
        while vm.virtio_ports:
            port = vm.virtio_ports.pop()
            portdev = vm.devices.get_by_params({"name": port.qemu_id})[0]
            (result, ver_out) = vm.devices.simple_unplug(portdev, vm.monitor)
            if not ver_out:
                test.fail("Can't unplug port %s: %s" % (port, result))
        session = vm.wait_for_login()

        # Power off the computer
        try:
            vm.reboot(
                session=session,
                method=params.get("virtio_console_method", "shell"),
                timeout=720,
            )
        except Exception as details:
            test.fail("Fail to reboot VM:\n%s" % details)

        # TODO: Hotplug ports and verify that they are usable
        # VM is missing ports, which are in params.
        vm.destroy(gracefully=True)

    @error_context.context_aware
    def test_failed_boot():
        """
        Start VM and check if it failed with the right error message.
        :param cfg: virtio_console_params - Expected error message.
        :param cfg: qemu_version_pattern - Qemu version pattern for high version.
        :param cfg: max_ports_invalid - Invalid max ports nums for different versions.
        :param cfg: max_ports_valid - Valid max ports nums for different versions.

        """
        max_ports_invalid = params["max_ports_invalid"].split(",")
        max_ports_valid = params["max_ports_valid"].split(",")

        qemu_version_pattern = params["qemu_version_pattern"]
        qemu_binary = utils_misc.get_qemu_binary(params)
        output = str(process.run(qemu_binary + " --version", shell=True))
        re_comp = re.compile(r"\s\d+\.\d+\.\d+")
        output_list = re_comp.findall(output)
        # high version
        if re.search(qemu_version_pattern, output_list[0]):
            params["extra_params"] = params["extra_params"] % (
                get_virtio_serial_name(),
                max_ports_invalid[0],
            )
            exp_error_message = params["virtio_console_params"] % max_ports_valid[0]
        else:
            params["extra_params"] = params["extra_params"] % (
                get_virtio_serial_name(),
                max_ports_invalid[1],
            )
            exp_error_message = params["virtio_console_params"] % max_ports_valid[1]

        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        try:
            vm.create(params=params)
        except Exception as details:
            if exp_error_message in str(details):
                test.log.info("Expected qemu failure. Test PASSED.")
                return
            else:
                test.fail(
                    "VM failed to start but error messages "
                    "don't match.\nExpected:\n%s\nActual:\n%s"
                    % (exp_error_message, details)
                )
        test.fail("VM started even though it should fail.")

    #
    # Debug and dummy tests
    #
    @error_context.context_aware
    def test_delete_guest_script():
        """
        This dummy test only removes the guest_worker_script. Use this it
        when you use the old image with a new guest_worker version.
        :note: The script name might differ!
        """
        vm = env.get_vm(params["main_vm"])
        session = vm.wait_for_login()
        out = session.cmd_output("echo on")
        if "on" in out:  # Linux
            session.cmd_status("killall python")
            session.cmd_status("rm -f /tmp/guest_daemon_*")
            session.cmd_status("rm -f /tmp/virtio_console_guest.py*")
        else:  # Windows
            session.cmd_status("del /F /Q C:\\virtio_console_guest.py*")

    #
    # Main
    # Executes test specified by virtio_console_test variable in cfg
    #
    fce = None
    _fce = "test_" + params.get("virtio_console_test", "").strip()
    error_context.context("Executing test: %s" % _fce, test.log.info)
    if _fce not in locals():
        test.cancel(
            "Test %s doesn't exist. Check 'virtio_console_"
            "test' variable in subtest.cfg" % _fce
        )
    else:
        try:
            fce = locals()[_fce]
            return fce()
        finally:
            EXIT_EVENT.set()
            vm = env.get_vm(params["main_vm"])
            if vm:
                vm.destroy()
