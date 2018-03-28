import logging
import re
import random

from virttest import data_dir
from virttest import storage
from virttest import utils_misc
from virttest.qemu_devices import qdevices
from virttest import qemu_qtree


def find_disk(vm, params):
    """
    Find all disks in guest.
    """
    if params.get("os_type") == "linux":
        pattern = params.get("get_disk_pattern")
        cmd = params.get("get_disk_cmd")
    elif params.get("os_type") == "windows":
        pattern = "^\d+"
        cmd = params.get("get_disk_index", "wmic diskdrive get index")

    session = vm.wait_for_login()
    output = session.cmd_output_safe(cmd)
    disks = re.findall(pattern, output, re.M)
    session.close()
    return disks


def find_image(params, image_name):
    """
    Find the path of the iamge.
    """
    image_params = params.object_params(image_name)
    o = storage.get_image_filename(image_params, data_dir.get_data_dir())
    return o


def get_new_disk(disk1, disk2):
    """
    Get the different disk between disk1 and disk2.
    """
    disk = list(set(disk2).difference(set(disk1)))
    return disk


def hotplug_device(vm, params, dev_contr_dict, num=0):
    """
    Hotplug device and verify it in qtree
    """
    pci_type = params.get("pci_type", "virtio_blk_pci")
    img_format_type = params.get("img_format_type", "qcow2")
    img_list = params.get("images").split()
    device = qdevices.QDevice(pci_type)
    err = ""
    if params.get("need_controller", "no") == "yes":
        controller_model = params.get("controller_model")
        controller = qdevices.QDevice(controller_model, params={"id":
                                      "hotadded_scsi%s" % num})
        bus_extra_param = params.get("bus_extra_params_%s" % img_list[num + 1])
        if bus_extra_param:
            for item in bus_extra_param.split():
                key, value = item.split("=", 1)
                qdevice_params = {key: value}
                controller.params.update(qdevice_params)
        controller.hotplug(vm.monitor)
        logging.info("Verify hotplug controller in qtree")
        ver_out = controller.verify_hotplug("", vm.monitor)
        if not ver_out:
            err = "%s is not in qtree after hotplug" % controller_model
            return err
        else:
            dev_contr_dict["contrs"].append(controller)

    drive = qdevices.QRHDrive("block%d" % num)
    drive.set_param("file", find_image(params, img_list[num + 1]))
    drive.set_param("format", img_format_type)
    drive_id = drive.get_param("id")
    drive.hotplug(vm.monitor)

    device.set_param("drive", drive_id)
    device.set_param("id", "block%d" % num)
    if params.get("need_controller", "no") == "yes" and bool(random.randrange(2)):
        device.set_param("bus", controller.get_param("id")+'.0')
    blk_extra_param = params.get("blk_extra_params_%s" % img_list[num + 1])
    if blk_extra_param:
        for item in blk_extra_param.split():
            key, value = item.split("=", 1)
            device.set_param(key, value)
    device.hotplug(vm.monitor)
    logging.info("Verify hotplug device in qtree")
    ver_out = device.verify_hotplug("", vm.monitor)
    if not ver_out:
        err = "%s is not in qtree after hotplug" % pci_type
        return err
    else:
        dev_contr_dict["devs"].append(device)

    if params.get("need_controller", "no") == "yes":
        info_qtree = vm.monitor.info('qtree', False)
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(info_qtree)
        for node in qtree.get_nodes():
            if node.qtree.get("id") == device.get_param("id"):
                try:
                    controller_id = node.parent.qtree.get("id").split(".")[0]
                except AttributeError:
                    err = "can't get parent of:\n%s" % node
                    return err
                dev_contr_dict["contr_dev_map"].setdefault(controller_id, []).append(device)
                break
        else:
            err = "Can't find device '%s' in qtree" % device.get_param("id")
            return err
    return err, dev_contr_dict


def check_device_in_guest(vm, params, plug_unplug, disks_before, blk_num=1):
    """
    check the plugged/unplugged block in guest
    """
    pause = float(params.get("virtio_block_pause", 10.0))
    if plug_unplug == "plug":
        plug_status = utils_misc.wait_for(lambda: len(get_new_disk(disks_before,
                                          find_disk(vm, params))) == blk_num, pause)
    else:
        plug_status = utils_misc.wait_for(lambda: len(get_new_disk(find_disk(vm, params),
                                          disks_before)) == blk_num, pause)
    return plug_status


def get_new_disks_in_guest(vm, params, disks_before):
    """
    Get new disks in guest after plug/unplug
    """
    disks_after = find_disk(vm, params)
    new_disks = get_new_disk(disks_before, disks_after)
    return new_disks


def unplug_device(vm, dev_contr_dict):
    """
    Unplug device and controller if exists
    """
    for controller in dev_contr_dict["contrs"]:
        controller_id = controller.get_param("id")
        for device in dev_contr_dict["contr_dev_map"].get(controller_id, []):
            device.unplug(vm.monitor)
            device.verify_unplug("", vm.monitor)
            dev_contr_dict["devs"].remove(device)
        controller.unplug(vm.monitor)
        controller.verify_unplug("", vm.monitor)
    for device in dev_contr_dict["devs"]:
        device.unplug(vm.monitor)
        device.verify_unplug("", vm.monitor)
