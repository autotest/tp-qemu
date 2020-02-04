import time
import logging

from avocado.utils import process
from virttest import error_context
from qemu.tests.virtio_serial_file_transfer import transfer_data
from qemu.tests.vioser_in_use import run_bg_test


@error_context.context_aware
def run(test, params, env):
    """
    Test hot unplug virtio serial devices.

     1) Start guest with virtio serial device(s).
     2) Run serial data trainsfer in background(windows only)
     3) Load module in guest os(linux only).
     4) For each of the virtio serial ports, do following steps one by one:
     4.1) Unload module in guest(linux only)
     4.2) Hot-unplug the virtio serial port
     4.3) Hotplug the devices
     4.4) Reload module in the guest(linux only)
     5) Repeat step2,3,4 100 times
     6) Run serial data transfer after repeated unplug/plug
     7) Reboot VM to make sure the guest kernel not panic.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    if params["os_type"] == "windows":
        run_bg_test(test, params, vm)
    for repeat in range(int(params.get("repeat_times", 1))):
        repeat += 1
        session = vm.wait_for_login(timeout=timeout)
        module = params.get("modprobe_module")
        if module:
            error_context.context("Load module %s" % module, logging.info)
            session.cmd("modprobe %s" % module)
        for port in params.objects("serials"):
            port_params = params.object_params(port)
            if not port_params['serial_type'].startswith('virt'):
                continue
            virtio_port = vm.devices.get(port)
            if not virtio_port:
                test.fail("Virtio Port '%s' not found" % port)
            chardev_qid = virtio_port.get_param("chardev")
            try:
                port_chardev = vm.devices.get_by_qid(chardev_qid)[0]
            except IndexError:
                test.error("Failed to get device %s" % chardev_qid)
            if module:
                error_context.context("Unload module %s" % module,
                                      logging.info)
                session.cmd("modprobe -r %s" % module)
            error_context.context("Unplug virtio port '%s' in %d tune(s)" %
                                  (port, repeat), logging.info)
            vm.devices.simple_unplug(virtio_port, vm.monitor)
            if port_params.get("unplug_chardev") == "yes":
                error_context.context(
                    "Unplug chardev '%s' for virtio port '%s'" %
                    (port, chardev_qid), logging.info)
                vm.devices.simple_unplug(port_chardev, vm.monitor)
                time.sleep(0.5)
                vm.devices.simple_hotplug(port_chardev, vm.monitor)
            vm.devices.simple_hotplug(virtio_port, vm.monitor)
            if module:
                error_context.context("Load  module %s" % module, logging.info)
                session.cmd("modprobe %s" % module)
        session.close()
    host_script = params['host_script']
    check_pid_cmd = 'pgrep -f %s' % host_script
    host_proc_pid = process.getoutput(check_pid_cmd, shell=True)
    if host_proc_pid:
        logging.info("Kill the first serial process on host")
        result = process.system('kill -9 %s' % host_proc_pid, shell=True)
        if result != 0:
            logging.error("Failed to kill the first serial process on host!")
    if transfer_data(params, vm) is not True:
        test.fail("Serial data transfter test failed.")
    vm.reboot()
    vm.verify_kernel_crash()
    session = vm.wait_for_login(timeout=timeout)
    session.close()
