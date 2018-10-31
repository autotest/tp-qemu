import time
import logging
import threading
import random
from collections import deque

from virttest import funcatexit
from virttest import qemu_virtio_port
from virttest.utils_virtio_port import VirtioPortTest

from qemu.tests.virtio_port_login import ConsoleLoginTest

EXIT_EVENT = threading.Event()


def _set_exit_event():
    """
    Sets global EXIT_EVENT
    :note: Used in cleanup by funcatexit
    """
    logging.info("Executing _set_exit_event()")
    EXIT_EVENT.set()


def run(test, params, env):
    """
    KVM virtio_console test

    1. boot guest with virtio-serial port and virtio-console
    2. login the guest via virtio-console
    3. transfer data via virtio-serial, during data transfer logout and re-login

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    virtio_test = VirtioPortTest(test, env, params)
    vm, guest_worker = virtio_test.get_vm_with_worker()
    console = virtio_test.get_virtio_ports(vm)[0][0].name
    serialports = virtio_test.get_virtio_ports(vm)[1]
    send_port = serialports[0]
    recv_port = serialports[1]
    params["login_console"] = console
    login_test = ConsoleLoginTest(test, env, params)
    logging.info("Login guest via virtio console: %s" % console)
    #Login guest via console
    session = login_test.console_login(console)

    # Transfer data via serial port
    threads = []
    queues = []
    queues.append(deque())
    blocklen = 1024
    send_port.open()
    recv_port.open()
    global EXIT_EVENT
    funcatexit.register(env, params.get('type'), _set_exit_event)
    send_thread = qemu_virtio_port.ThSendCheck(send_port, EXIT_EVENT,
                                               queues, blocklen)
    send_thread.start()
    threads.append(send_thread)
    recv_thread = qemu_virtio_port.ThRecvCheck(recv_port, queues,
                                               EXIT_EVENT, blocklen)
    recv_thread.start()
    threads.append(recv_thread)

    # Logout and re-login the console session
    def _close_session():
        """Close session with random sleep before and after that"""
        time.sleep(random.randrange(1, 20))
        if session:
            session.close()
        time.sleep(random.randrange(1, 20))

    _close_session()
    session = login_test.console_login(console)
    _close_session()

    # Stop the data transfer threads
    EXIT_EVENT.set()
    funcatexit.unregister(env, params.get('type'), _set_exit_event)
    err = ""
    try:
        for thread in threads:
            thread.join(5)
            if thread.ret_code:
                err += "Error occurred in thread: %s; " % thread
        if err:
            test.fail(err)
        # Handle exception when threads still not exit
        for thread in threads:
            if thread.isAlive():
                logging.debug("Unable to destroy the thread %s", thread)
                vm.destroy()
                del threads[:]
                test.error("Not all threads finished.")
    finally:
        virtio_test.cleanup(vm, guest_worker)
        vm.verify_kernel_crash()
