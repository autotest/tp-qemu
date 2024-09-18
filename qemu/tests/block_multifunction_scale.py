from virttest import env_process, error_context

from provider.block_devices_plug import BlockDevicesPlug
from qemu.tests.block_multifunction import io_test, set_addr


@error_context.context_aware
def run(test, params, env):
    """
    Hotplug many disks with multifunction on.

    1） Boot guest with system disk(multifunction=on)
    2） Hotplug disks with addr 0x0.0x1~0xn.0x7
    3） Check disks in guest
    4） Run iozone test on all data disks for Windows guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def generate_image(dev_slots, plug, params, qdev, image_size, pcie, test):
        """
        Generate the data disk devices to be plugged

        :param dev_slots: All the slots to be plugged
        :param plug: BlockDevicesPlug
        :param params: vm.params
        :param qdev: DevContainer
        :param image_size: The image size to be specified
        :param pcie: if itis pcie bus
        """
        disks = []
        for slot in dev_slots:
            scsi_bus = 1
            parent_bus = "pcie_extra_root_port_%s" % slot if pcie else "pci.0"
            images = []
            for i in range(1, 9):
                stg = "stg%s%s" % (slot, i)
                images.append(stg)
                params["images"] += " %s" % stg
                params["image_name_%s" % stg] = "images/%s" % stg
                params["image_size_%s" % stg] = image_size
                params["remove_image_%s" % stg] = "yes"
                params["force_create_image_%s" % stg] = "no"
                params["create_image_%s" % stg] = "yes"
                params["boot_drive_%s" % stg] = "no"
                # Specify the address of the device, plug them into same slot
                addr = 0 if pcie else slot
                set_addr(stg, addr, i, params)
                if params["drive_format"].startswith("scsi"):
                    # Create oen new scsi bus for each block device
                    params["drive_bus_%s" % stg] = scsi_bus
                    scsi_bus += 1
            env_process.process_images(env_process.preprocess_image, test, params)
            parent_bus_obj = qdev.get_buses({"aobject": parent_bus})[0]
            plug._hotplug_devs(images, vm.monitor, bus=parent_bus_obj)
            disks.extend(plug)
        return disks

    image_size = "500M"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    qdev = vm.devices
    windows = params["os_type"] == "windows"
    disk_op_cmd = params.get("disk_op_cmd")
    session = vm.wait_for_login()
    pcie = False
    if "q35" in params["machine_type"] or "arm64-pci" in params["machine_type"]:
        pcie = True
    dev_slots = range(0, 3) if pcie else (7, 10)

    plug = BlockDevicesPlug(vm)
    disks = generate_image(dev_slots, plug, vm.params, qdev, image_size, pcie, test)
    if windows:
        io_test(session, disk_op_cmd, disks, windows, image_size)
