import logging
import re

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

    def run_sub_test(params, plug_tag):
        """
        Run subtest before/after hotplug/unplug device.

        :param plug_tag: identify when to run subtest,
                         ex, before_hotplug.
        :return: whether vm was successfully shut-down
                 if needed
        """
        sub_type = params.get("sub_type_%s" % plug_tag)
        if sub_type:
            error_context.context(context_msg % (sub_type, plug_tag),
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)
            if sub_type == "shutdown" and vm.is_dead():
                return True
        return None

    img_list = params.get("images").split()
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
        error_context.context("Hotplug block device (iteration %d)" % iteration,
                              logging.info)

        plug_tag = "before_plug"
        run_sub_test(params, plug_tag)

        session = vm.wait_for_login(timeout=timeout)
        for num in range(blk_num):
            image_name = img_list[num + 1]
            image_params = params.object_params(image_name)
            if params.get("need_plug") == "yes":
                disks_before_plug = find_disk(vm, get_disk_cmd)
                devs = vm.devices.images_define_by_params(image_name,
                                                          image_params, 'disk')
                for dev in devs:
                    ret = vm.devices.simple_hotplug(dev, vm.monitor)
                    if ret[1] is False:
                        test.fail("Failed to hotplug device '%s'."
                                  "Output:\n%s" % (dev, ret[0]))
                plug_disks = utils_misc.wait_for(lambda: get_new_disk(disks_before_plug,
                                                 find_disk(vm, get_disk_cmd)), pause)
                if not plug_disks:
                    test.fail("Failed to hotplug device to guest")
                disk = plug_disks[0]

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
                        test.fail("Check for block device failed."
                                  "Output: %s" % output)

                devs = [dev for dev in devs if not isinstance(dev, qdevices.QDrive)]
                device_list.extend(devs)
            else:
                for device in vm.devices:
                    if device.get_param("id") == img_list[num + 1]:
                        device_list.append(device)
        session.close()

        plug_tag = "after_plug"
        vm_switched_off = run_sub_test(params, plug_tag)
        if vm_switched_off:
            return

        plug_tag = "before_unplug"
        run_sub_test(params, plug_tag)

        error_context.context("Unplug block device (iteration %d)" % iteration,
                              logging.info)
        disks_before_unplug = find_disk(vm, get_disk_cmd)
        for device in reversed(device_list):
            ret = vm.devices.simple_unplug(device, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to unplug device '%s'."
                          "Output:\n%s" % (device, ret[0]))

        unplug_disks = utils_misc.wait_for(lambda: get_new_disk(find_disk(vm, get_disk_cmd),
                                           disks_before_unplug), pause)
        if len(unplug_disks) != blk_num:
            test.fail("Failed to unplug devices from guest, need to unplug: %d,"
                      "actual unplug: %d" % (blk_num, len(unplug_disks)))

        plug_tag = "after_unplug"
        run_sub_test(params, plug_tag)
