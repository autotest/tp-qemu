from virttest import error_context

from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Boot vm with virtio device:virtio-blk-pci, virtio-scsi-pci, virtio-net-pci
    and use aer=on for virtio devices.

    1) Boot guest with virtio-blk-pci, virtio-scsi-pci, virtio-net-pci device,
       and use aer=on,ats=on for virtio devices.
    2) check if aer and ats capabilitie in guest os

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def get_pci_addr_by_devid(dev_id):
        """
        Get pci address by device id.
        """

        def _get_device_by_devid(devices, dev_id):
            """
            Get device info with device id from 'info pci' output.
            """
            device_found = {}
            for dev in devices:
                if dev["qdev_id"] == dev_id:
                    device_found = dev
                    break
                elif dev["class_info"].get("desc") == "PCI bridge":
                    pci_bridge_devices = dev["pci_bridge"].get("devices")
                    if not pci_bridge_devices:
                        continue
                    device_found = _get_device_by_devid(pci_bridge_devices, dev_id)
                    if device_found:
                        break
            return device_found

        dev_addr = ""
        dev_addr_fmt = "%02d:%02d.%d"
        pci_info = vm.monitor.info("pci", debug=False)
        device = _get_device_by_devid(pci_info[0]["devices"], dev_id)
        if device:
            dev_addr = dev_addr_fmt % (
                device["bus"],
                device["slot"],
                device["function"],
            )
        return dev_addr

    def check_dev_cap_in_guest(dev_id, capbilities):
        """
        Check the specified device's capabilities in guest os

        :params dev_id: device id in qemu command line
        :params capbilities: the capabilities list that expected to be found
        :return True if get all the capabilities, else False
        """

        dev_addr = get_pci_addr_by_devid(dev_id)
        for cap in capbilities:
            check_cmd = "lspci -vvv -s %s | grep '%s'" % (dev_addr, cap)
            if session.cmd_status(check_cmd) != 0:
                test.log.error(
                    "Failed to get capability '%s' for device %s", cap, dev_id
                )
                return False
        return True

    if params.object_params("qmpmonitor1").get("monitor_type") == "human":
        test.cancel("Please run test with qmp monitor")

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    capabilities = params["capabilities"].split(",")
    images = params.objects("images")

    dev_ids = []
    blk_image = images[1]
    blk_dev = vm.devices.get_by_qid(blk_image)[0]
    blk_dev_id = blk_dev.params["id"]
    dev_ids.append(blk_dev_id)

    scsi_dev = vm.devices.get_by_params({"driver": "virtio-scsi-pci"})[0]
    scsi_dev_id = scsi_dev.params["id"]
    dev_ids.append(scsi_dev_id)

    nic_id = vm.virtnet[0].device_id
    nic_dev = vm.devices.get_by_qid(nic_id)[0]
    nic_dev_id = nic_dev.params["id"]
    dev_ids.append(nic_dev_id)

    try:
        for dev_id in dev_ids:
            if not check_dev_cap_in_guest(dev_id, capabilities):
                test.fail(
                    "Check capabilities %s for device %s failed"
                    % (capabilities, dev_id)
                )

        plug = BlockDevicesPlug(vm)
        for img in params.get("hotplug_images", "").split():
            plug.unplug_devs_serial(img)
            plug.hotplug_devs_serial(img)
            blk_dev = vm.devices.get_by_qid(img)[0]
            blk_dev_id = blk_dev.params["id"]
            if not check_dev_cap_in_guest(blk_dev_id, capabilities):
                test.fail(
                    "Check capabilities %s for device %s failed"
                    % (capabilities, blk_dev_id)
                )
    finally:
        session.close()
