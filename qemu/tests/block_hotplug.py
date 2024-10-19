import logging
import re

from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_numeric, utils_test
from virttest.qemu_capabilities import Flags
from virttest.qemu_devices import qdevices

LOG_JOB = logging.getLogger("avocado.test")


def find_all_disks(session, windows):
    """Find all disks in guest."""
    global all_disks
    if windows:
        all_disks = set(session.cmd("wmic diskdrive get index").split()[1:])
    else:
        all_disks = utils_misc.list_linux_guest_disks(session)
    return all_disks


def wait_plug_disks(session, action, disks_before_plug, excepted_num, windows, test):
    """Wait plug disks completely."""
    if not utils_misc.wait_for(
        lambda: len(disks_before_plug ^ find_all_disks(session, windows))
        == excepted_num,
        60,
        step=1.5,
    ):
        disks_info_win = (
            "wmic logicaldisk get drivetype,name,description "
            "& wmic diskdrive list brief /format:list"
        )
        disks_info_linux = "lsblk -a"
        disks_info = session.cmd(disks_info_win if windows else disks_info_linux)
        LOG_JOB.debug("The details of disks:\n %s", disks_info)
        test.fail(
            "Failed to {0} devices from guest, need to {0}: {1}, "
            "actual {0}: {2}".format(
                action, excepted_num, len(disks_before_plug ^ all_disks)
            )
        )
    return disks_before_plug ^ all_disks


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

    def run_sub_test(test_name):
        """Run subtest before/after hotplug/unplug device."""
        error_context.context("Running sub test '%s'." % test_name, test.log.info)
        utils_test.run_virt_sub_test(test, params, env, test_name)

    def create_block_devices(image):
        """Create block devices."""
        return vm.devices.images_define_by_params(
            image, params.object_params(image), "disk"
        )

    def get_block_devices(objs):
        """Get block devices."""
        if isinstance(objs, str):
            return [dev for dev in vm.devices if dev.get_param("id") == objs]
        dtype = (
            qdevices.QBlockdevNode
            if vm.check_capability(Flags.BLOCKDEV)
            else qdevices.QDrive
        )
        return [dev for dev in objs if not isinstance(dev, dtype)]

    def plug_block_devices(action, plug_devices):
        """Plug block devices."""
        error_context.context(
            "%s block device (iteration %d)" % (action.capitalize(), iteration),
            test.log.info,
        )
        session = vm.wait_for_login(timeout=timeout)
        disks_before_plug = find_all_disks(session, windows)
        plug_devices = plug_devices if action == "hotplug" else plug_devices[::-1]
        for dev in plug_devices:
            ret = getattr(vm.devices, "simple_%s" % action)(dev, vm.monitor)
            if ret[1] is False:
                test.fail("Failed to %s device '%s', %s." % (action, dev, ret[0]))

        num = 1 if action == "hotplug" else len(data_imgs)
        plugged_disks = wait_plug_disks(
            session, action, disks_before_plug, num, windows, test
        )
        session.close()
        return plugged_disks

    def format_disk_win():
        """Format disk in windows."""
        error_context.context("Format disk %s in windows." % new_disk, test.log.info)  # pylint: disable=E0606
        session = vm.wait_for_login(timeout=timeout)
        if disk_index is None and disk_letter is None:
            drive_letters.append(
                utils_disk.configure_empty_windows_disk(
                    session, new_disk, params["image_size_%s" % img]
                )[0]
            )
        elif disk_index and disk_letter:
            utils_misc.format_windows_disk(
                session, disk_index[index], disk_letter[index]
            )
            drive_letters.append(disk_letter[index])
        session.close()

    def run_io_test():
        """Run io test on the hot plugged disks."""
        error_context.context("Run io test on the hot plugged disks.", test.log.info)
        session = vm.wait_for_login(timeout=timeout)
        if windows:
            drive_letter = drive_letters[index]
            test_cmd = disk_op_cmd % (drive_letter, drive_letter)
            test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
        else:
            test_cmd = disk_op_cmd % (new_disk, new_disk)
        session.cmd(test_cmd, timeout=disk_op_timeout)
        session.close()

    def get_disk_size(did):
        """
        Get the disk size from guest.

        :param did: the disk of id, e.g. sdb,sda for linux, 1, 2 for windows
        :return: the disk size
        """
        session = vm.wait_for_login(timeout=timeout)
        if windows:
            script = "{}_{}".format("disk", utils_misc.generate_random_string(6))
            cmd = "echo %s > {0} && diskpart /s {0} && del /f {0}".format(script)
            p = r"Disk\s+%s\s+[A-Z]+\s+(?P<size>\d+\s+[A-Z]+)\s+"
            disk_info = session.cmd(cmd % "list disk")
            size = (
                re.search(p % did, disk_info, re.I | re.M).groupdict()["size"].strip()
            )
        else:
            size = utils_disk.get_linux_disks(session)[did][1].strip()
        test.log.info("The size of disk %s is %s", did, size)
        session.close()
        return size

    def check_disk_size(did, excepted_size):
        """
        Checkt whether the disk size is equal to excepted size.

        :param did: the disk of id, e.g. sdb,sda for linux, 1, 2 for windows
        :param excepted_size: the excepted size
        """
        error_context.context(
            "Check whether the size of the disk[%s] hot plugged is equal to "
            "excepted size(%s)." % (did, excepted_size),
            test.log.info,
        )
        value, unit = re.search(r"(\d+\.?\d*)\s*(\w?)", excepted_size).groups()
        if utils_numeric.normalize_data_size(get_disk_size(did), unit) != value:
            test.fail(
                "The size of disk %s is not equal to excepted size(%s)."
                % (did, excepted_size)
            )

    data_imgs = params.get("images").split()[1:]
    disk_index = params.objects("disk_index")
    disk_letter = params.objects("disk_letter")
    disk_op_cmd = params.get("disk_op_cmd")
    disk_op_timeout = int(params.get("disk_op_timeout", 360))
    timeout = int(params.get("login_timeout", 360))
    windows = params["os_type"] == "windows"

    sub_test_after_plug = params.get("sub_type_after_plug")
    sub_test_after_unplug = params.get("sub_type_after_unplug")
    sub_test_before_unplug = params.get("sub_type_before_unplug")
    shutdown_after_plug = sub_test_after_plug == "shutdown"
    need_plug = params.get("need_plug", "no") == "yes"
    need_check_disk_size = params.get("check_disk_size", "no") == "yes"

    drive_letters = []
    unplug_devs = []
    global all_disks
    all_disks = set()

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    for iteration in range(int(params.get("repeat_times", 3))):
        try:
            for index, img in enumerate(data_imgs):
                data_devs = create_block_devices(img)
                if need_plug:
                    new_disk = plug_block_devices("hotplug", data_devs).pop()

                    if windows:
                        if iteration == 0:
                            format_disk_win()
                    if need_check_disk_size:
                        check_disk_size(
                            new_disk if windows else new_disk[5:],
                            params["image_size_%s" % img],
                        )

                    if disk_op_cmd:
                        run_io_test()
                unplug_devs.extend(
                    get_block_devices(data_devs)
                    if need_plug
                    else get_block_devices(img)
                )

            if sub_test_after_plug:
                run_sub_test(sub_test_after_plug)
            if shutdown_after_plug:
                return

            if sub_test_before_unplug:
                run_sub_test(sub_test_before_unplug)

            plug_block_devices("unplug", unplug_devs)
            del unplug_devs[:]

            if sub_test_after_unplug:
                run_sub_test(sub_test_after_unplug)
        except Exception as e:
            pid = vm.get_pid()
            test.log.debug("Find %s Exception:'%s'.", pid, str(e))
            if pid:
                logdir = test.logdir
                process.getoutput("gstack %s > %s/gstack.log" % (pid, logdir))
                process.getoutput(
                    "timeout 20 strace -tt -T -v -f -s 32 -p %s -o "
                    "%s/strace.log" % (pid, logdir)
                )
            else:
                test.log.debug("VM dead...")
            raise e
