import re
import logging

from virttest import error_context
from virttest import utils_misc
from virttest import utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test hot unplug of PCI devices.

    1) Set up test environment in host if test sr-iov.
    2) Start VM.
    3) Get the device id that want to unplug.
    4) Delete the device, verify whether could remove the PCI device.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def find_pci():
        output = vm.monitor.info("qtree")
        devices = re.findall(match_string, output)
        return devices

    # Hot delete a pci device
    def pci_del(device, ignore_failure=False):
        def _device_removed():
            after_del = vm.monitor.info("pci")
            return after_del != before_del

        before_del = vm.monitor.info("pci")
        if cmd_type == "device_del":
            cmd = "device_del id=%s" % device
            vm.monitor.send_args_cmd(cmd)
        else:
            test.fail("device_del command is not supported")

        if (not utils_misc.wait_for(_device_removed, test_timeout, 0, 1) and
                not ignore_failure):
            test.fail("Failed to hot remove PCI device: %s. "
                      "Monitor command: %s" % (pci_model, cmd))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("test_timeout", 360))
    # Test if it is nic or block
    pci_num = int(params.get("unplug_pci_num", 1))
    pci_model = params.get("pci_model", "pci-assign")
    # Need udpate match_string if you use a card other than 82576
    match_string = params.get("match_string", "dev: %s, id \"(.*)\"")
    match_string = match_string % pci_model

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        error_context.context("modprobe the module %s" % module, logging.info)
        session.cmd("modprobe %s" % module)

    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == "qmp":
        cmd_o = vm.monitor.info("commands")
    else:
        cmd_o = vm.monitor.send_args_cmd("help")
    if not cmd_o:
        test.error("Unknown version of qemu")

    cmd_type = utils_misc.find_substring(str(cmd_o), "device_del")

    devices = find_pci()
    context_msg = "Running sub test '%s' %s"
    sub_type = params.get("sub_type_before_unplug")
    if sub_type:
        error_context.context(context_msg % (sub_type, "before unplug"),
                              logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    if devices:
        for device in devices[:pci_num]:
            # (lmr) I think here is the place where pci_info should go
            pci_info = []
            error_context.context("Hot unplug device %s" % device,
                                  logging.info)
            pci_del(device)

    sub_type = params.get("sub_type_after_unplug")
    if sub_type:
        error_context.context(context_msg % (sub_type, "after hotunplug"),
                              logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type)
