import re
import logging
import string
from autotest.client.shared import error, utils
from virttest import utils_misc, aexpect, storage, utils_test, data_dir, arch
from virttest import qemu_qtree, qemu_virtio_port


@error.context_aware
def run(test, params, env):
    """
    Test hotplug of virtio serial.

    1) Start VM with one virtio serial bus and two ports.
    2) Transferring data from guest to host via two serial ports.
    3) Hot unplug two serial ports.
    4) Hot plug two serial ports back.
    5) Repeat step 3 and 4 in a loop during step 2.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def device_add(driver, device_id, bus=None, chardev=None, name=None):
        add_cmd = "device_add driver=%s,id=%s" % (driver, device_id)
        if chardev:
            add_cmd += ",chardev=%s" % chardev
        if name:
            add_cmd += ",name=%s" % name
        if bus:
            add_cmd += ",bus=%s" % bus
        add_output = vm.monitor.send_args_cmd(add_cmd, convert=False)
        after_add = vm.monitor.info("qtree")
        if device_id not in str(after_add):
            logging.error("Could not find matched id in monitor:"
                          " %s" % device_id)
            raise error.TestFail("Add device failed. Monitor command is: %s"
                                 ". Output: %r" % (add_cmd, add_output))

    def find_device_in_qtree(device_id, key, value):
        serial_ports = filter_device_from_qtree(key, value)
        found = False
        for port in serial_ports:
            if device_id == port["id"]:
                found = True
                break
        return found

    def device_del(device_id, key="type", value="virtserialport",
                   ignore_failure=False):
        def _device_removed():
            found = find_device_in_qtree(device_id, key, value)
            return not found

        cmd = "device_del id=%s" % device_id
        vm.monitor.send_args_cmd(cmd)
        if (not utils_misc.wait_for(_device_removed, test_timeout, 0, 1) and
                not ignore_failure):
            serial_ports = filter_device_from_qtree(key, value)
            raise error.TestFail("Failed to hot remove device: %s. "
                                 "Monitor command: %s" %
                                 (device_id, cmd))

    def hotunplug(hotplug_ports, chardevs):
        for port in hotplug_ports:
            port_info = {}
            serial_ports = filter_device_from_qtree("type", "virtserialport")
            for s_port in serial_ports:
                if port == s_port["name"].strip('"'):
                    port_info = s_port
            if not port_info:
                txt = "Could not find %s in qemu qtree." % port
                txt += " qemu virtio serial port: %s\n" % serial_ports
                raise error.TestFail(txt)

            sub_type = params.get("sub_type_before_unplug")
            if sub_type:
                error.context(context_msg % (sub_type, "before hotunplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error.context("start hot-deleting serial port %s" % port,
                          logging.info)
            device_id = port_info["id"]
            unplug_bus = params.get("unplug_bus_%s" % port, "no") == "yes"
            device_del(device_id)
            for _port in vm.virtio_ports:
                if _port.name == port:
                    vm.virtio_ports.remove(_port)

            if unplug_bus:
                bus_id = params.get("bus_%s" % port)
                error.context("start hot-deleting serial bus %s" % bus_id,
                              logging.info)
                device_del(bus_id, "type", "virtio-serial-pci")
            chardevs.append(port_info["chardev"].strip('"'))
            sub_type = params.get("sub_type_after_unplug")
            if sub_type:
                error.context(context_msg % (sub_type, "after hotunplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

    def hotplug(hotplug_ports, driver, chardevs):
        buses = filter_device_from_qtree("type", "virtio-serial-bus")
        tested_port = []
        for port in hotplug_ports:
            chardev = chardevs.pop(-1)
            bus = params.get("bus_%s" % port)
            if not bus:
                bus = buses[0]["id"]
            else:
                if bus not in buses:
                    error.context("Start hot-adding serial bus %s" % bus,
                                  logging.info)
                    bus_driver = params.get("serial_bus_driver")
                    device_add(bus_driver, bus)
                    buses = filter_device_from_qtree("type", "virtio-serial-bus")
                    for _bus in buses:
                        if bus in _bus["id"]:
                            bus = _bus["id"]
            sub_type = params.get("sub_type_before_plug")
            if sub_type:
                error.context(context_msg % (sub_type, "before hotplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error.context("Start hot-adding serial port %s" % port,
                          logging.info)
            name = port
            device_id = port
            device_add(driver, device_id, bus, chardev, name)
            tested_port.append(port)
            filename = filter_chardev_filename(vm, chardev)
            if params.get('virtio_port_type') in ("console",
                                                  "virtio_console"):
                vm.virtio_ports.append(
                    qemu_virtio_port.VirtioConsole(name, name,
                                                   filename))
            else:
                vm.virtio_ports.append(
                    qemu_virtio_port.VirtioSerial(name, name,
                                                  filename))

            sub_type = params.get("sub_type_after_plug")
            if sub_type:
                error.context(context_msg % (sub_type, "after hotplug"),
                              logging.info)
                params["file_transfer_serial_ports"] = " ".join(tested_port)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

    def filter_device_from_qtree(keyword, value):
        devices = []
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info('qtree'))
        for qdev in qtree.get_nodes():
            if keyword in qdev.qtree and qdev.qtree[keyword] == value:
                devices.append(qdev.qtree)
        return devices

    def filter_chardev_filename(vm, device_id):
        re_string = "-chardev \S+,id=%s,path=([/0-9a-zA-Z\-_]+)" % device_id
        return re.findall(re_string, vm.qemu_command)[0]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    test_timeout = int(params.get("hotplug_timeout", 360))
    hotplug_ports = params["hotplug_ports"].split()
    hotplug_driver = params.get("hotplug_driver", "virtserialport")
    bus_type = params.get("bus_type", "virtio-serial-bus")
    rp_times = int(params.get("hotplug_repeat_times", 1))

    session = vm.wait_for_login(timeout=timeout)

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        session.cmd("modprobe %s" % module)

    context_msg = "Running sub test '%s' %s"
    sub_type = params.get("sub_type_during_plug")
    thread = None
    during_run_flag = params.get("during_plug_run_flag")
    env[during_run_flag] = False

    serial_ports = filter_device_from_qtree("type", hotplug_driver)
    chardevs = []
    if params.get("unplug_first", "no") == "yes":
        for port in serial_ports:
            chardev = port["chardev"].strip('"')
            chardevs.append(chardev)
    for chardev in params.objects("chardevs"):
        chardev_params = params.object_params(chardev)
        chardev_id = chardev_params.get("chardev_id")
        if not chardev_id:
            chardev_id = "id_%s" % chardev
        chardevs.append(chardev_id)

    if sub_type:
        error.context(context_msg % (sub_type, "during hotplug"),
                      logging.info)
        thread = utils.InterruptedThread(utils_test.run_virt_sub_test,
                                         (test, params, env, sub_type, None))
        thread.start()
        if not utils_misc.wait_for(lambda: env.get(during_run_flag),
                                   60, 0, 1,
                                   "Wait %s test start" % sub_type):
            err = "Fail to start %s test" % sub_type
            raise error.TestError(err)

    try:
        for num in range(rp_times):
            logging.info("Start hot-plug/hot-unplug serial port, repeat %s",
                         num + 1)
            if params.get("unplug_first", "no") == "yes":
                hotunplug(hotplug_ports, chardevs)
                hotplug(hotplug_ports, hotplug_driver, chardevs)
            else:
                hotplug(hotplug_ports, hotplug_driver, chardevs)
                hotunplug(hotplug_ports, chardevs)
    finally:
        if thread:
            thread.join()

    if params.get("reboot_vm", "no") == "yes":
        vm.reboot()
