import logging
import re

from virttest import error_context
from virttest import utils_misc
from virttest import utils_disk
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
    def _find_disks(session):
        """
        Find all disks in guest.

        :return: The set of all disks.
        :rtype: Set.
        """
        if os_type == "linux":
            disks = utils_misc.list_linux_guest_disks(session)
        elif os_type == "windows":
            disks = set(session.cmd('wmic diskdrive get index').split()[1:])
        else:
            test.cancel("Unsupported OS type '%s'" % os_type)
        return disks

    def _get_new_disk(disk1, disk2):
        """
        Get the different disk between disk1 and disk2.

        :param disk1: The set of disk1.
        :type disk1: Set.
        :param disk2: The set of disk2.
        :type disk2: Set.
        :return: A new set with disks in either the disk1 or disk2 but not both.
        :rtype: Set
        """
        return disk1 ^ disk2

    def run_sub_test(name):
        """
        Run subtest before/after hotplug/unplug device.

        :param name: identify when to run subtest, e,g, before_hotplug.
        :return: whether vm was successfully shut-down if needed.
        """
        sub_type = params.get("sub_type_%s" % name)
        if sub_type:
            error_context.context(
                "Running sub test '%s' %s" % (sub_type, name), logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_type)

    def check_unplugged_disks(session, disks_before_unplug):
        """ Check the unplungged disks. """
        unplug_disks = utils_misc.wait_for(
            lambda: _get_new_disk(disks_before_unplug, _find_disks(session)),
            pause)
        if unplug_disks is None:
            unplug_disks = set()
        if len(unplug_disks) != extra_disks_num:
            return False
        return True

    def create_block_devices(image_name):
        """ Create block devices. """
        return vm.devices.images_define_by_params(
            image_name, params.object_params(image_name), 'disk')

    def get_block_devices(objs):
        """ Get block devices. """
        if isinstance(objs, str):
            devs = [dev for dev in vm.devices if dev.get_param("id") == objs]
        else:
            devs = [dev for dev in objs if not isinstance(dev, qdevices.QDrive)]
        devices.extend(devs)

    def hotplug_block_devices(devices):
        """ Hot plug block devices. """
        error_context.context(
            "Hotplug block device (iteration %d)" % iteration, logging.info)
        session = vm.wait_for_login(timeout=timeout)
        disks_before_plug = _find_disks(session)
        for device in devices:
            ret = vm.devices.simple_hotplug(device, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to hotplug device '%s'."
                          "Output:\n%s" % (device, ret[0]))
        plug_disk = utils_misc.wait_for(
            lambda: _get_new_disk(disks_before_plug, _find_disks(session)),
            pause)
        if plug_disk is None:
            test.fail("Failed to hotplug device to guest")
        session.close()
        return plug_disk.pop()

    def unplug_block_devices(devices):
        """ Unplug block devices. """
        error_context.context(
            "Unplug block device (iteration %d)" % iteration, logging.info)
        session = vm.wait_for_login(timeout=timeout)
        disks_before_unplug = _find_disks(session)
        for device in reversed(devices):
            ret = vm.devices.simple_unplug(device, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to unplug device '%s'."
                          "Output:\n%s" % (device, ret[0]))
        unplug_disks = set()
        if not utils_misc.wait_for(
                lambda: check_unplugged_disks(session, disks_before_unplug),
                pause):
            test.fail(
                "Failed to unplug devices from guest, need to unplug: %d, "
                "actual unplug: %d" % (extra_disks_num, len(unplug_disks)))
        session.close()

    def format_disk_win():
        """ Format disk in windows. """
        error_context.context("Format disk %s in windows." % disk, logging.info)
        session = vm.wait_for_login(timeout=timeout)
        drive_letters.append(
            utils_disk.configure_empty_windows_disk(
                session, disk, utils_disk.SIZE_AVAILABLE)[0])
        # For run "block_resize" sub test, assign disk_index and disk_letter.
        session.close()

    def _add_assign_letter():
        """ Add assign option for umount_disk in disk_update_cmd. """
        params['disk_update_cmd'] = re.sub(r'--op=umount_disk',
                                           '--op=umount_disk --assign=%s' %
                                           drive_letters[0],
                                           params['disk_update_cmd'])

    def disk_io_test():
        """ Do disk io test on disk. """
        error_context.context("Do disk io test on hotplug disk.", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        if os_type == "linux":
            test_cmd = disk_op_cmd.format(disk)
        elif os_type == "windows":
            if iteration == 0:
                format_disk_win()
                if params.get('disk_update_cmd'):
                    _add_assign_letter()
            test_cmd = disk_op_cmd.format(drive_letters[index - 1])
            test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
        else:
            test.cancel("Unsupported OS type '%s'" % os_type)
        session.cmd(test_cmd, timeout=disk_op_timeout)
        session.close()

    imgs = params.get("images").split()
    os_type = params["os_type"]
    #sometimes, ppc can't get new plugged disk in 5s, so time to 10s
    pause = float(params.get("virtio_block_pause", 10.0))
    extra_disks_num = len(imgs) - 1
    repeat_times = int(params.get("repeat_times", 3))
    timeout = int(params.get("login_timeout", 360))
    disk_op_cmd = params.get("disk_op_cmd")
    disk_op_timeout = int(params.get("disk_op_timeout", 360))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    drive_letters = []
    for iteration in range(repeat_times):
        devices = []
        run_sub_test("before_plug")
        for index in range(1, len(imgs)):
            if params.get("need_plug", 'no') == "yes":
                devs = create_block_devices(imgs[index])
                disk = hotplug_block_devices(devs)
                if disk_op_cmd:
                    disk_io_test()
                get_block_devices(devs)
            else:
                get_block_devices(imgs[index])
        run_sub_test("after_plug")
        if not vm.is_alive():
            break
        run_sub_test("before_unplug")
        unplug_block_devices(devices)
        run_sub_test("after_unplug")
