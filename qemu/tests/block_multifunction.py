import logging

from avocado.core import exceptions

from virttest import env_process
from virttest import error_context
from virttest import utils_misc
from virttest import utils_disk
from virttest.qemu_monitor import QMPCmdError
from virttest.qemu_devices.qdevices import QDevice, QDrive

from qemu.tests import block_hotplug
from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test multi disk with multifunction on and off.

    1） Boot guest with system disk(multifunction=on)
    2） Hotplug 7 disks with addr 0x0.0x1~0x0.0x7
    3） hotplug 1 disk with multifunction=on (addr 0x0)
    4） Check disks in guest
    5） Run dd/iozone test on all data disks
    6) Reboot guest, check disks in guest
    7) Unplug disk8, and remove disk 1-7
    8) Hotplug disk8 with multifunction=off

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def set_addr(image_name, slot, function, multifunction='on', vm=None):
        """
        Specify the multifunciton address for image device

        :param image_name: The image to be assigned address
        :param slot: The slot of address
        :param function: The function of addresss
        :param multifunction: on/off
        :param vm: The VM object
        """
        params_obj = vm.params if vm else params
        if params_obj['drive_format'].startswith('scsi'):
            param_name = 'bus_extra_params_%s' % image_name
        else:
            param_name = 'blk_extra_params_%s' % image_name
        if function % 8 == 0:
            logging.info('Set multifunction=on for %s' % image_name)
            params_obj[param_name] = 'multifunction=%s' % multifunction
            if function == 0:
                return
        addr_pattern = 'addr=%s.%s' % (hex(slot), hex(function % 8))
        logging.info('Set addr of %s to %s' % (image_name, addr_pattern))
        extra_param = params_obj.get(param_name)
        if extra_param:
            params_obj[param_name] = extra_param + ',' + addr_pattern
        else:
            params_obj[param_name] = addr_pattern

    def get_image_device(qdev, img_name):
        """
        Get the image device(virtio-blk-pci/virtio-scsi-pci)
        :param qdev: DevContainer object
        :param img_name: The image name
        """
        dev = qdev.get(img_name)
        devs = [dev]
        if params['drive_format'].startswith('scsi'):
            devs.append(qdev.get_by_properties(
                {'aid': dev.get_param('bus').split('.')[0]})[0])
        return devs

    image = params.objects('images')[0]
    vm_name = params['main_vm']
    set_addr(image, 0, 0)  # Add multifunction=on option before start vm
    params['start_vm'] = 'yes'
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    qdev = vm.devices
    windows = params["os_type"] == 'windows'
    disk_op_cmd = params.get("disk_op_cmd")
    session = vm.wait_for_login()

    q35 = params['machine_type'] == 'q35'
    dev_slot = 0 if q35 else 9
    parent_bus = 'pcie_extra_root_port_0' if q35 else 'pci.0'
    image_size = '1G'
    # Generate the data disk devices to be plugged
    for i in range(1, 9):
        stg = 'stg%s' % i
        vm.params['images'] += ' %s' % stg
        vm.params['image_name_%s' % stg] = 'images/%s' % stg
        vm.params['image_size_%s' % stg] = image_size
        vm.params['remove_image_%s' % stg] = 'yes'
        vm.params['force_create_image_%s' % stg] = 'yes'
        vm.params['boot_drive_%s' % stg] = 'no'
        # Specify the address of the device, plug them into same slot
        set_addr(stg, dev_slot, i, vm=vm)
        if params['drive_format'].startswith('scsi'):
            # Create oen new scsi bus for each block device
            vm.params['drive_bus_%s' % stg] = i
    # To create those image files
    env_process.process_images(env_process.preprocess_image, test, vm.params)

    plug = BlockDevicesPlug(vm)
    parent_bus_obj = qdev.get_buses({'aobject': parent_bus})[0]
    plug.hotplug_devs_serial(bus=parent_bus_obj)

    # Run io test on all the plugged disks
    for index, disk in enumerate(plug):
        if windows:
            if not utils_disk.update_windows_disk_attributes(session, disk):
                test.fail("Failed to clear readonly for all disks and online "
                          "them in guest")
            partition = utils_disk.configure_empty_windows_disk(
                session, disk, image_size)
            test_cmd = disk_op_cmd % (partition[0], partition[0])
            test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
        else:
            test_cmd = disk_op_cmd % (disk, disk)
        session.cmd(test_cmd, timeout=360)

    # Reboot the guest and check if all the disks still exist
    disks_before_reboot = block_hotplug.find_all_disks(session, windows)
    session = vm.reboot(session)
    block_hotplug.wait_plug_disks(
        session, 'check', disks_before_reboot, 0, windows, test)
    session.close()

    # Unplug the disk on function 7 and 0, and check if all the disks been removed
    images = vm.params.objects('images')
    unplug_dev = images[-1]
    unplug_timeout = params['unplug_timeout']
    try:
        plug.unplug_devs_serial(images=unplug_dev, timeout=unplug_timeout)
    except exceptions.TestError as e:
        if 'Actual: 8 disks. Expected: ' not in str(e):
            raise
    else:
        test.fail('All the plugged disks should be removed when'
                  ' the device at function 0 is removed.')

    # replug disk 2-7
    rest_dev = images[1:-1]
    # Remove them from DevContainer first, they are unplugged by qemu
    # but still in DevContainer
    for img in rest_dev:
        devs_rm = get_image_device(qdev, img)
        list(map(lambda x: qdev.remove(x, recursive=False), devs_rm))
    plug._create_devices(rest_dev, {'aobject': parent_bus})
    for img, devs in plug._hotplugged_devs.items():
        if img not in rest_dev:
            continue
        for dev in devs:
            args = (dev, vm.monitor)
            if isinstance(dev, QDevice):
                pci_device = qdev.is_pci_device(dev['driver'])
                if pci_device:
                    args += (parent_bus_obj,)
                elif not dev['driver'].startswith('scsi'):
                    continue
            elif not isinstance(dev, QDrive):
                continue
            try:
                plug._hotplug_atomic(*args)
            except NotImplementedError:
                # Insert might fail for file node 1-7 not been removed
                # from vm.devices, which can be ignored
                pass

    # Replug disk 8 on slot 0 with multifunction='off'
    set_addr(images[-1], dev_slot, 0, multifunction='off', vm=vm)
    plug._create_devices(unplug_dev.split(), {'aobject': parent_bus})
    for img, devs in plug._hotplugged_devs.items():
        for dev in devs:
            if (img == images[-1] and
                    isinstance(dev, QDevice) and
                    qdev.is_pci_device(dev['driver'])):
                dev['addr'] = hex(dev_slot)  # for pci bus addr might be reset
                try:
                    parent_bus_obj.prepare_hotplug(dev)
                    dev.hotplug(vm.monitor)
                except QMPCmdError as e:
                    if 'single function' not in str(e):
                        raise
                else:
                    test.fail('It should fail to hotplug a single function device'
                              ' to the address where multifunction already on.')
                break
            else:
                plug._hotplug_atomic(dev, vm.monitor)
