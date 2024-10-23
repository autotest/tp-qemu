import errno
import os
import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Under named-pipe non-blocking testing:
    1) Create pipe named by the following
    2) Boot up a single-CPU guest with a virtio-serial device and
       named-pipe chardev backend
    3) Write data to the virtio-serial port until the guest stops.
    4) check whether guest can work.
    5) Read the named-pipe file on the host.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    timeout = float(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    serials = params["serials"].split()
    v_path = vm.get_serial_console_filename(serials[-1])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    out_put = session.cmd_output(
        "nohup cat /proc/kallsyms > /dev/virtio-ports/vs2 2>&1 &"
    )
    time.sleep(10)
    if session.cmd_output("date") is None:
        test.fail("Guest shouldn't be blocked and a date should output!")
    guest_pid = out_put.split()[1]
    pipe = os.open(v_path, os.O_RDONLY | os.O_NONBLOCK)
    while True:
        try:
            os.read(pipe, 1)
        except OSError as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                time.sleep(5)
                break
            else:
                raise Exception("Read data in host failed as %s" % e)

    if not session.cmd_status("ps -p %s" % guest_pid, safe=True):
        test.fail(
            "send process in guest does not exit after all data are read out in host"
        )
    vm.verify_alive()
    vm.verify_kernel_crash()
