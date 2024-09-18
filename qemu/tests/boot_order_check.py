import re
import time

from avocado.utils import process
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM Autotest set boot order for multiple NIC and block devices
    1) Boot the vm with deciding bootorder for multiple block and NIC devices
    2) Check the guest boot order, should try to boot guest os
       from the device whose bootindex=1, if this fails, it
       should try device whose bootindex=2, and so on, till
       the guest os succeeds to boot or fails to boot

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def _get_device(devices, dev_id):
        device_found = {}
        for dev in devices:
            if dev["qdev_id"] == dev_id:
                device_found = dev
                break
            elif dev["class_info"].get("desc") == "PCI bridge":
                pci_bridge_devices = dev["pci_bridge"].get("devices")
                if not pci_bridge_devices:
                    continue
                device_found = _get_device(pci_bridge_devices, dev_id)
                if device_found:
                    break
        return device_found

    def _get_pci_addr_by_devid(dev_id):
        dev_addr = ""
        dev_addr_fmt = "%02d:%02d.%d"
        pci_info = vm.monitor.info("pci", debug=False)
        if isinstance(pci_info, list):
            device = _get_device(pci_info[0]["devices"], dev_id)
            if device:
                dev_addr = dev_addr_fmt % (
                    device["bus"],
                    device["slot"],
                    device["function"],
                )
        else:
            # As device id in the last line of info pci output
            # We need reverse the pci information to get the pci addr which is in the
            # front row.
            pci_list = str(pci_info).split("\n")
            pci_list.reverse()
            pci_info = " ".join(pci_list)
            dev_match = re.search(nic_addr_filter % dev_id, pci_info)
            if dev_match:
                bus_slot_func = [int(i) for i in dev_match.groups()]
                dev_addr = dev_addr_fmt % tuple(bus_slot_func)
        return dev_addr

    error_context.context("Boot vm by passing boot order decided", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.pause()

    # Disable nic device, boot fail from nic device except user model
    if params["nettype"] != "user":
        for nic in vm.virtnet:
            process.system("ifconfig %s down" % nic.ifname)

    vm.resume()
    devices_load_timeout = int(params.get("devices_load_timeout", 10))

    timeout = int(params.get("login_timeout", 240))
    params.get("bootorder_type")
    boot_fail_infos = params.get("boot_fail_infos")
    bootorder = params.get("bootorder")
    nic_addr_filter = params.get("nic_addr_filter")
    output = None
    result = None
    list_nic_addr = []

    for nic in vm.virtnet:
        boot_index = params["bootindex_%s" % nic.nic_name]
        pci_addr = utils_misc.wait_for(
            lambda: _get_pci_addr_by_devid(nic.device_id), timeout=devices_load_timeout
        )
        if not pci_addr:
            test.fail("Cannot get the pci address of %s." % nic.nic_name)
        list_nic_addr.append((pci_addr, boot_index))

    list_nic_addr.sort(key=lambda x: x[1])

    boot_fail_infos = boot_fail_infos % (
        list_nic_addr[0][0],
        list_nic_addr[1][0],
        list_nic_addr[2][0],
    )

    error_context.context("Check the guest boot result", test.log.info)
    start = time.time()
    while True:
        if params["enable_sga"] == "yes":
            output = vm.serial_console.get_stripped_output()
        else:
            output = vm.serial_console.get_output()
        result = re.findall(boot_fail_infos, output, re.S | re.I)
        if result or time.time() > start + timeout:
            break
        time.sleep(1)
    if not result:
        test.fail(
            "Timeout when try to get expected boot order: "
            "'%s', actual result: '%s'" % (bootorder, output)
        )
