import re
import time
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_misc
from virttest import utils_test
from virttest.qemu_devices import qdevices


@error.context_aware
def run(test, params, env):
    """
    Test hot unplug virtio serial devices.

    1) Start guest with virtio serial device(s).
    2) reload module in guest os.
    3) Hot-unplug virtio serial port one by one.
    4) unload module in guest
    5) Hotplug it one by one.
    6) reload module in guest.
    7) Reboot VM to check guest kernel not panic.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def get_virtio_port_by_name(vm, name):
        """
        Get virtio port object by name in VM.

        :param name: name of the port
        """
        for device in vm.devices:
            if isinstance(device, qdevices.QDevice):
                if device.get_param("name") == name:
                    return device
        return None

    def get_virtio_port_name_by_params(params, tag):
        """
        Get virtio port name via params according tag.

        :param params: test params.
        :param tag: port name or tag(eg, vc1).
        """
        prefix = params.get('virtio_port_name_prefix')
        index = params.objects("virtio_ports").index(tag)
        if prefix:
            return "%s%d" % (prefix, index)
        return tag

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    for repeat in xrange(int(params.get("repeat_times", 1))):
        repeat += 1
        session = vm.wait_for_login(timeout=timeout)
        module = params.get("modprobe_module")
        if module:
            error.context("modporbe the module %s" % module, logging.info)
            session.cmd("modprobe %s" % module)
        for port in params.objects("virtio_ports"):
            port_params = params.object_params(port)
            port_name = get_virtio_port_name_by_params(port_params, port)
            virtio_port = get_virtio_port_by_name(vm, port_name)
            chardev_qid = virtio_port.get_param("chardev")
            port_chardev = vm.devices.get_by_qid(chardev_qid)[0]
            if module:
                error.context("modporbe the module %s" % module, logging.info)
                session.cmd("modprobe -r %s" % module)
            error.context("Unplug virtio port '%s' in %d tune(s)" %
                          (port, repeat), logging.info)
            virtio_port.unplug(vm.monitor)
            if port_params.get("unplug_chardev") == "yes":
                error.context(
                    "Unplug chardev '%s' for virtio port '%s'" %
                    (port, chardev_qid), logging.info)
                port_chardev.unplug(vm.monitor)
                time.sleep(0.5)
                port_chardev.hotplug(vm.monitor)
            virtio_port.hotplug(vm.monitor)
            if module:
                error.context("modprobe the module %s" % module, logging.info)
                session.cmd("modprobe %s" % module)
        vm.reboot()
        session = vm.wait_for_login(timeout=timeout)
        session.close()
