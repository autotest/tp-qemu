import logging
import re
import time

from avocado.utils import process

from virttest import error_context


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
    error_context.context("Boot vm by passing boot order decided",
                          logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.pause()

    # Disable nic device, boot fail from nic device except user model
    if params['nettype'] != 'user':
        for nic in vm.virtnet:
            process.system("ifconfig %s down" % nic.ifname)

    vm.resume()

    timeout = int(params.get("login_timeout", 240))
    bootorder_type = params.get("bootorder_type")
    boot_fail_infos = params.get("boot_fail_infos")
    bootorder = params.get("bootorder")
    nic_addr_filter = params.get("nic_addr_filter")
    output = None
    result = None
    list_nic_addr = []

    # As device id in the last line of info pci output
    # We need reverse the pci information to get the pci addr which is in the
    # front row.
    pci_info = vm.monitor.info("pci")
    nic_slots = {}
    if isinstance(pci_info, list):
        pci_devices = pci_info[0]['devices']
        for device in pci_devices:
            if device['class_info']['desc'] == "Ethernet controller":
                nic_slots[device['qdev_id']] = device['slot']
    else:
        pci_list = str(pci_info).split("\n")
        pci_list.reverse()
        pci_info = " ".join(pci_list)

    for nic in vm.virtnet:
        if nic_slots:
            nic_addr = nic_slots[nic.device_id]
        else:
            nic_addr = re.findall(nic_addr_filter % nic.device_id,
                                  pci_info)[0]
        nic_addr = "0%s" % nic_addr
        bootindex = int(params['bootindex_%s' % nic.nic_name])
        list_nic_addr.append((nic_addr[-2:], bootindex))

    list_nic_addr.sort(key=lambda x: x[1])

    boot_fail_infos = boot_fail_infos % (list_nic_addr[0][0],
                                         list_nic_addr[1][0],
                                         list_nic_addr[2][0])

    error_context.context("Check the guest boot result", logging.info)
    start = time.time()
    while True:
        output = vm.serial_console.get_stripped_output()
        result = re.findall(boot_fail_infos, output, re.S | re.I)
        if result or time.time() > start + timeout:
            break
        time.sleep(1)
    if not result:
        test.fail("Timeout when try to get expected boot order: "
                  "'%s', actual result: '%s'" % (bootorder, output))
