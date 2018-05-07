import logging
import re
import random

from virttest import data_dir
from virttest import storage
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test
from virttest.qemu_devices import qdevices
from virttest import qemu_qtree


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest with/without block device(s).
    2) Hoplug block device and verify
    3) Do read/write data on hotplug block.
    4) Unplug block device and verify

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def find_image(image_name):
        """
        Find the path of the iamge.
        """
        image_params = params.object_params(image_name)
        o = storage.get_image_filename(image_params, data_dir.get_data_dir())
        return o

    def find_disk(vm, cmd):
        """
        Find all disks in guest.
        """
        if params.get("os_type") == "linux":
            pattern = params.get("get_disk_pattern", "^/dev/vd[a-z]*$")
        elif params.get("os_type") == "windows":
            pattern = r"^\d+"
            cmd = params.get("get_disk_index", "wmic diskdrive get index")
        else:
            test.cancel("Unsupported OS type '%s'" % params.get("os_type"))

        session = vm.wait_for_login(timeout=timeout)
        output = session.cmd_output_safe(cmd)
        disks = re.findall(pattern, output, re.M)
        session.close()
        return disks

    def get_new_disk(disk1, disk2):
        """
        Get the different disk between disk1 and disk2.
        """
        disk = list(set(disk2).difference(set(disk1)))
        return disk

    def unplug_device(vm, get_disk_cmd, device):
        """
        Unplug device
        """
        disks_before_unplug = find_disk(vm, get_disk_cmd)
        device.unplug(vm.monitor)
        event_status = utils_misc.wait_for(
            lambda: vm.monitor.get_event(params.get('event_name')),
            params.get('event_timeout'), 0.0,
            float(params.get('check_interval')))

        if not event_status:
            test.fail("Can not get event \"%s\" under %s."
                      % (params.get('event_name'), params.get('event_timeout')))
        else:
            logging.debug("Get event \"%s\" info after unplug device: \n%s"
                          % (params.get('event_name'),
                             vm.monitor.get_event(params.get('event_name'))))
            vm.monitor.clear_event(params.get('event_name'))

        device.verify_unplug("", vm.monitor)
        unplug_status = utils_misc.wait_for(lambda: len(get_new_disk(find_disk
                                            (vm, get_disk_cmd), disks_before_unplug)) != 0, pause)
        return unplug_status

    img_list = params.get("images").split()
    img_format_type = params.get("img_format_type", "qcow2")
    pci_type = params.get("pci_type", "virtio-blk-pci")
    #sometimes, ppc can't get new plugged disk in 5s, so time to 10s
    pause = float(params.get("virtio_block_pause", 10.0))
    blk_num = int(params.get("blk_num", 1))
    repeat_times = int(params.get("repeat_times", 3))
    timeout = int(params.get("login_timeout", 360))
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    get_disk_cmd = params.get("get_disk_cmd")
    context_msg = "Running sub test '%s' %s"
    disk_index = params.objects("disk_index")
    disk_letter = params.objects("disk_letter")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    for iteration in range(repeat_times):
        device_list = []
        controller_list = []
        controller_device_dict = {}
        error_context.context("Hotplug block device (iteration %d)" % iteration,
                              logging.info)

        sub_type = params.get("sub_type_before_plug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "before hotplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        for num in range(blk_num):
            device = qdevices.QDevice(pci_type)
            if params.get("need_plug") == "yes":
                disks_before_plug = find_disk(vm, get_disk_cmd)

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
                    ver_out = controller.verify_hotplug("", vm.monitor)
                    if not ver_out:
                        err = "%s is not in qtree after hotplug" % controller_model
                        test.fail(err)
                    else:
                        controller_list.append(controller)

                drive = qdevices.QRHDrive("block%d" % num)
                drive.set_param("file", find_image(img_list[num + 1]))
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
                ver_out = device.verify_hotplug("", vm.monitor)
                if not ver_out:
                    err = "%s is not in qtree after hotplug" % pci_type
                    test.fail(err)
                plug_status = utils_misc.wait_for(lambda: len(get_new_disk(disks_before_plug,
                                                  find_disk(vm, get_disk_cmd))) != 0, pause)
                if plug_status:
                    disks_after_plug = find_disk(vm, get_disk_cmd)
                    new_disks = get_new_disk(disks_before_plug, disks_after_plug)
                else:
                    test.fail("Can't get new disks")
                if params.get("need_controller", "no") == "yes":
                    info_qtree = vm.monitor.info('qtree', False)
                    qtree = qemu_qtree.QtreeContainer()
                    qtree.parse_info_qtree(info_qtree)
                    for node in qtree.get_nodes():
                        if node.qtree.get("id") == device.get_param("id"):
                            try:
                                controller_id = node.parent.qtree.get("id").split(".")[0]
                            except AttributeError:
                                test.fail("can't get parent of:\n%s" % node)
                            controller_device_dict.setdefault(controller_id, []).append(device)
                            break
                    else:
                        test.fail("Can't find device '%s' in qtree" % device.get_param("id"))
            else:
                if params.get("drive_format") in pci_type:
                    get_disk_cmd += " | egrep -v '^/dev/[hsv]da[0-9]*$'"

                device.set_param("id", img_list[num + 1])
                new_disks = find_disk(vm, get_disk_cmd)

            device_list.append(device)
            if not new_disks:
                test.fail("Cannot find new disk after hotplug.")

            if params.get("need_plug") == "yes":
                disk = new_disks[0]
            else:
                disk = new_disks[num]

            session = vm.wait_for_login(timeout=timeout)
            if params.get("os_type") == "windows":
                if iteration == 0:
                    error_context.context("Format disk", logging.info)
                    utils_misc.format_windows_disk(session, disk_index[num],
                                                   mountpoint=disk_letter[num])
            error_context.context("Check block device after hotplug.",
                                  logging.info)
            if params.get("disk_op_cmd"):
                if params.get("os_type") == "linux":
                    test_cmd = params.get("disk_op_cmd") % (disk, disk)
                elif params.get("os_type") == "windows":
                    test_cmd = params.get("disk_op_cmd") % (disk_letter[num],
                                                            disk_letter[num])
                    test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
                else:
                    test.cancel("Unsupported OS type '%s'" % params.get("os_type"))

                status, output = session.cmd_status_output(test_cmd,
                                                           timeout=disk_op_timeout)
                if status:
                    test.fail("Check for block device failed "
                              "after hotplug, Output: %r" % output)
            session.close()

        sub_type = params.get("sub_type_after_plug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "after hotplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
            if sub_type == "shutdown" and vm.is_dead():
                return

        sub_type = params.get("sub_type_before_unplug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "before unplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        error_context.context("Unplug block device (iteration %d)" % iteration,
                              logging.info)
        for controller in controller_list:
            controller_id = controller.get_param("id")
            for device in controller_device_dict.get(controller_id, []):
                unplug_status = unplug_device(vm, get_disk_cmd, device)
                if not unplug_status:
                    test.fail("Failed to unplug disks '%s'" % device.get_param("id"))
                device_list.remove(device)
            controller.unplug(vm.monitor)
        for device in device_list:
            unplug_status = unplug_device(vm, get_disk_cmd, device)
            if not unplug_status:
                test.fail("Failed to unplug disks '%s'" % device.get_param("id"))

        sub_type = params.get("sub_type_after_unplug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "after unplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
