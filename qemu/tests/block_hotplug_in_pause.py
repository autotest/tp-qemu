import logging
import re

from virttest import error_context
from virttest import utils_misc
from virttest import utils_disk
from virttest.qemu_devices import qdevices


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up guest.
    2) Stop vm
    3) Hotplug device and verify in qtree
    4) Resume vm
    5) Check hotplug devices in guest
    6) Stop vm (for case: without_plug)
    7) Unplug device and verify in qtree
    8) Resume vm
    9) Check unplug device in guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    def find_disk(session, cmd):
        """
        Find all disks in guest.

        :param cmd: cmd to get disks in guest
        :return: disks in guest.
        """
        if params.get("os_type") == "linux":
            pattern = params.get("get_disk_pattern", "^/dev/[vs]d[a-z]*$")
        elif params.get("os_type") == "windows":
            pattern = r"^\d+\s+\d+"
        else:
            test.cancel("Unsupported OS type '%s'" % params.get("os_type"))

        output = session.cmd_output_safe(cmd)
        disks = re.findall(pattern, output, re.M)
        return disks

    def get_plug_unplug_disks(disk1, disk2):
        """
        Get the different disk between disk1 and disk2.

        :param disk1: Disks before hotplug/unplug
        :param disk2: Disks after hotplug/unplug.
        :return: List of hotplug/unplug disks.
        """
        disk = list(set(disk2) ^ (set(disk1)))
        return disk

    def block_hotplug(image_name):
        """
        Hotplug disks and verify it in qtree.

        :param image_name: Image name of hotplug disk
        :return: List of objects for hotplug disk.
        """
        image_params = params.object_params(image_name)
        devs = vm.devices.images_define_by_params(image_name,
                                                  image_params, 'disk')
        for dev in devs:
            ret = vm.devices.simple_hotplug(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to hotplug device '%s'."
                          "Output:\n%s" % (dev, ret[0]))
        devs = [dev for dev in devs if not isinstance(dev, qdevices.QDrive)]
        return devs

    def block_unplug(device_list):
        """
        Unplug disks and verify it in qtree

        :param device_list: List of objectes for unplug disks
        """
        for dev in reversed(device_list):
            ret = vm.devices.simple_unplug(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to unplug device '%s'."
                          "Ouptut:\n%s" % (dev, ret[0]))

    def block_check_in_guest(session, disks, blk_num,
                             get_disk_cmd, plug_tag="hotplug"):
        """
        Check hotplug/unplug disks in guest

        :param session: A shell session object.
        :param disks: List of disks before hotplug/unplug.
        :param blk_num: Number of hotplug/unplug disks.
        :param get_disk_cmd: Cmd to get disks info in guest.
        :param plug_tag: Tag for hotplug/unplug
        """
        logging.info("Check block device in guest after %s." % plug_tag)
        pause = float(params.get("virtio_block_pause", 30.0))
        status = utils_misc.wait_for(lambda: len(get_plug_unplug_disks(disks,
                                     find_disk(session, get_disk_cmd))) == blk_num,
                                     pause)
        disks = get_plug_unplug_disks(disks, find_disk(session, get_disk_cmd))
        if not status:
            test.fail("Failed to %s device to guest, expected: %d,"
                      "actual: %d" % (plug_tag, blk_num, len(disks)))

    def get_windows_drive_letters(session, index_sizes):
        """
        Format windows disk and get drive_letter for empty disks

        :param session: A shell session object.
        :param index_sizes: List for hotplug disk's index_size
        """
        drive_indexs = []
        for item in index_sizes:
            drive_indexs.append(item.split()[0])
        if not utils_disk.update_windows_disk_attributes(session, drive_indexs):
            test.fail("Failed to clear readonly for all disks and online "
                      "them in guest")
        error_context.context("Format disk", logging.info)
        for item in index_sizes:
            did, size = item.split()
            drive_letter = utils_disk.configure_empty_windows_disk(session,
                                                                   did, size + "B")
            windows_drive_letters.extend(drive_letter)

    def rw_disk_in_guest(session, plug_disks, iteration):
        """
        Do read/write on hotplug disks

        :param session: A shell session object.
        :param plug_disks: List for hotplug disks
        :param iteration: repeat times for hotplug.
        """
        if params.get("os_type") == "windows":
            if iteration == 0:
                get_windows_drive_letters(session, plug_disks)
            plug_disks = windows_drive_letters

        logging.info("Read/Writ on block device after hotplug.")
        disk_op_timeout = int(params.get("disk_op_timeout", 360))
        for disk in plug_disks:
            if params.get("os_type") not in ["linux", "windows"]:
                test.cancel("Unsupported OS type '%s'" % params.get("os_type"))
            else:
                test_cmd = params.get("disk_op_cmd") % (disk, disk)
                if params.get("os_type") == "windows":
                    test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
            status, output = session.cmd_status_output(test_cmd,
                                                       timeout=disk_op_timeout)
            if status:
                test.fail("Check for block device rw failed."
                          "Output: %s" % output)

    blk_num = int(params.get("blk_num", 1))
    repeat_times = int(params.get("repeat_times", 3))
    get_disk_cmd = params.get("get_disk_cmd")
    img_list = params.get("images").split()
    windows_drive_letters = []

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    for iteration in range(repeat_times):
        device_list = []
        if params.get("need_plug") == "yes":
            error_context.context("Run block hotplug/unplug for iteration:"
                                  "%d" % iteration, logging.info)
            error_context.context("Plug device", logging.info)
            disks_before_plug = find_disk(session, get_disk_cmd)

            if params.get("stop_vm_before_hotplug", "no") == "yes":
                error_context.context("Stop VM before hotplug")
                vm.pause()

            for num in range(blk_num):
                image_name = img_list[num + 1]
                devs = block_hotplug(image_name)
                if devs:
                    device_list.extend(devs)

            if vm.is_paused() and params.get("resume_vm_after_hotplug", "yes") == "yes":
                error_context.context("Resume vm after hotplug")
                vm.resume()

                block_check_in_guest(session, disks_before_plug, blk_num, get_disk_cmd)
                if params.get("disk_op_cmd"):
                    plug_disks = get_plug_unplug_disks(disks_before_plug,
                                                       find_disk(session, get_disk_cmd))
                    rw_disk_in_guest(session, plug_disks, iteration)

        else:
            for device in vm.devices:
                for img in img_list[1:]:
                    if device.get_param("id") == img:
                        device_list.append(device)

        error_context.context("Unplug device", logging.info)
        if not vm.is_paused():
            disks_before_unplug = find_disk(session, get_disk_cmd)
            if params.get("stop_vm_before_unplug", "yes") == "yes":
                error_context.context("Stop vm before unplug")
                vm.pause()
        else:
            blk_num = 0
            disks_before_unplug = disks_before_plug
        block_unplug(device_list)

        if vm.is_paused():
            error_context.context("Resume vm after unplug")
            vm.resume()

        block_check_in_guest(session, disks_before_unplug,
                             blk_num, get_disk_cmd, plug_tag="unplug")

    session.close()
