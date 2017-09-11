import logging
import re
import time

from virttest import data_dir
from virttest import storage
from virttest import error_context
from virttest import utils_misc
from virttest import utils_test
from virttest.qemu_devices import qdevices


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
            pattern = "^\d+"
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

    img_list = params.get("images").split()
    img_format_type = params.get("img_format_type", "qcow2")
    pci_type = params.get("pci_type", "virtio-blk-pci")
    pause = float(params.get("virtio_block_pause", 5.0))
    blk_num = int(params.get("blk_num", 1))
    repeat_times = int(params.get("repeat_times", 3))
    timeout = int(params.get("login_timeout", 360))
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    get_disk_cmd = params.get("get_disk_cmd")
    context_msg = "Running sub test '%s' %s"
    device_list = []
    disk_index = params.objects("disk_index")
    disk_letter = params.objects("disk_letter")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    for iteration in xrange(repeat_times):
        error_context.context("Hotplug block device (iteration %d)" % iteration,
                              logging.info)

        sub_type = params.get("sub_type_before_plug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "before hotplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        for num in xrange(blk_num):
            device = qdevices.QDevice(pci_type)
            if params.get("need_plug") == "yes":
                if params.get("need_controller", "no") == "yes":
                    controller_model = params.get("controller_model")
                    controller = qdevices.QDevice(controller_model)
                    controller.hotplug(vm.monitor)
                    ver_out = controller.verify_hotplug("", vm.monitor)
                    if not ver_out:
                        err = "%s is not in qtree after hotplug" % controller_model
                        test.fail(err)

                disks_before_plug = find_disk(vm, get_disk_cmd)

                drive = qdevices.QRHDrive("block%d" % num)
                drive.set_param("file", find_image(img_list[num + 1]))
                drive.set_param("format", img_format_type)
                drive_id = drive.get_param("id")
                drive.hotplug(vm.monitor)

                device.set_param("drive", drive_id)
                device.set_param("id", "block%d" % num)
                device.hotplug(vm.monitor)
                ver_out = device.verify_hotplug("", vm.monitor)
                if not ver_out:
                    err = "%s is not in qtree after hotplug" % pci_type
                    test.fail(err)
                time.sleep(pause)

                disks_after_plug = find_disk(vm, get_disk_cmd)
                new_disks = get_new_disk(disks_before_plug, disks_after_plug)
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
            if vm.is_dead():
                return

        sub_type = params.get("sub_type_before_unplug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "before unplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

        for num in xrange(blk_num):
            error_context.context("Unplug block device (iteration %d)" % iteration,
                                  logging.info)
            device_list[num].unplug(vm.monitor)
            device_list[num].verify_unplug("", vm.monitor)
            time.sleep(pause)

        sub_type = params.get("sub_type_after_unplug")
        if sub_type:
            error_context.context(context_msg % (sub_type, "after unplug"),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
