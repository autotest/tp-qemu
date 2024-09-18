import re

from virttest import error_context
from virttest.qemu_monitor import QMPCmdError


@error_context.context_aware
def run(test, params, env):
    """
    Hot-unplug/Hot-plug virtio-blk-pci, virtio-scsi-pci, virtio-net-pci while
    the parent pcie-root-port use 'hotplug=off'

    1) Boot guest with virtio-blk-pci, virtio-scsi-pci, virtio-net-pci device,
       and the parent pcie-root-port use 'hotplug=off'
    2) Hot unplug those devices
    3) Hot plug new virtio-blk-pci, virtio-scsi-pci, virtio-net-pci device to
       pcie-root-port that use 'hotplug=off'

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def hotplug_blk():
        """
        Hot-plug virtio-blk-pci
        """
        virtio_blk_pci_dev = image_devs[-1]
        virtio_blk_pci_dev.set_param("bus", free_root_port_id)
        virtio_blk_pci_dev.hotplug(vm.monitor, vm.devices.qemu_version)

    def hotplug_scsi():
        """
        Hot-plug virtio-scsi-pci
        """
        pci_add_cmd = "device_add driver=virtio-scsi-pci, id=plug"
        pci_add_cmd += ",bus=%s" % free_root_port_id
        vm.monitor.send_args_cmd(pci_add_cmd)

    def hotplug_nic():
        """
        Hot-plug virtio-net-pci
        """
        nic_name = "plug"
        nic_params = params.object_params(nic_name)
        nic_params["nic_model"] = "virtio-net-pci"
        nic_params["nic_name"] = nic_name
        vm.hotplug_nic(**nic_params)

    def unplug_device(device):
        """
        Hot unplug device

        :param device: QDevice object
        """
        parent_bus = device.get_param("bus")
        driver = device.get_param("driver")
        device.get_param("id")
        error_context.context("Hot-unplug %s" % driver, test.log.info)
        error_pattern = unplug_error_pattern % (parent_bus, parent_bus)
        try:
            device.unplug(vm.monitor)
        except QMPCmdError as e:
            if not re.search(error_pattern, e.data["desc"]):
                test.fail(
                    "Hot-unplug failed but '%s' isn't the expected error"
                    % e.data["desc"]
                )
            error_context.context(
                "Hot-unplug %s failed as expected: %s" % (driver, e.data["desc"]),
                test.log.info,
            )
        else:
            test.fail("Hot-unplug %s should not success" % driver)

    def plug_device(driver):
        """
        Hot plug device

        :param driver: the driver name
        """
        error_context.context("Hot-plug %s" % driver, test.log.info)
        error_pattern = hotplug_error_pattern % (free_root_port_id, free_root_port_id)
        try:
            callback[driver]()
        except QMPCmdError as e:
            if not re.search(error_pattern, e.data["desc"]):
                test.fail(
                    "Hot-plug failed but '%s' isn't the expected error" % e.data["desc"]
                )
            error_context.context(
                "Hot-plug %s failed as expected: %s" % (driver, e.data["desc"]),
                test.log.info,
            )
        else:
            test.fail("Hot-plug %s should not success" % driver)

    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()
    images = params.objects("images")
    hotplug_error_pattern = params.get("hotplug_error_pattern")
    unplug_error_pattern = params.get("unplug_error_pattern")
    unplug_devs = []

    blk_image = images[1]
    blk_pci_dev = vm.devices.get_by_qid(blk_image)[0]
    unplug_devs.append(blk_pci_dev)

    # In this case only one virtio-scsi-pci device, and the drive name is
    # fixed 'virtio-scsi-pci' for q35
    scsi_pci_dev = vm.devices.get_by_params({"driver": "virtio-scsi-pci"})[0]
    unplug_devs.append(scsi_pci_dev)

    nic_id = vm.virtnet[0].device_id
    nic_dev = vm.devices.get_by_qid(nic_id)[0]
    unplug_devs.append(nic_dev)
    for dev in unplug_devs:
        unplug_device(dev)

    # TODO: eject device in windows guest

    # one free root port is enough, use the default one provided by framework
    bus = vm.devices.get_buses({"aobject": "pci.0"})[0]
    free_root_port_dev = bus.get_free_root_port()
    free_root_port_id = free_root_port_dev.child_bus[0].busid
    plug_image = images[-1]
    plug_image_params = params.object_params(plug_image)
    image_devs = vm.devices.images_define_by_params(
        plug_image, plug_image_params, "disk"
    )
    error_context.context(
        "Hot-plug the Drive/BlockdevNode first, " "will be used by virtio-blk-pci",
        test.log.info,
    )
    for image_dev in image_devs[:-1]:
        vm.devices.simple_hotplug(image_dev, vm.monitor)

    callback = {
        "virtio-blk-pci": hotplug_blk,
        "virtio-scsi-pci": hotplug_scsi,
        "virtio-net-pci": hotplug_nic,
    }
    for driver in ["virtio-blk-pci", "virtio-scsi-pci", "virtio-net-pci"]:
        plug_device(driver)
