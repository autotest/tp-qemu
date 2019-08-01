import time
import logging

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test hot unplug virtio serial devices.

     1) Start guest with virtio serial device(s).
     2) Load module in guest os.
     3) For each of the virtio serial ports, do following steps one by one:
     3.1) Unload module in guest
     3.2) Hot-unplug the virtio serial port
     3.3) Hotplug the devices
     3.4) Reload module in the guest
     4) Repeat step2,3 100 times
     5) Reboot VM to make sure the guest kernel not panic.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
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
            port_chardev = vm.devices.get_by_qid(chardev_qid)[0]
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
    vm.reboot()
    session = vm.wait_for_login(timeout=timeout)
    session.close()
