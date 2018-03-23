import logging
import re

from autotest.client.shared import error

from virttest import utils_misc
from virttest import utils_test
from virttest import storage
from virttest import data_dir
from virttest.utils_windows import drive


def get_block_size(test, session, block_cmd, block_pattern):
    """
    Get the disk size inside guest.

    param block_cmd: run block_cmd command to get detail disk size info.
    param block_pattern: use this pattern to filter the needed.

    param return: return current block size.
    """
    output = session.cmd_output(block_cmd)
    block_size = re.findall(block_pattern, output)
    if block_size:
        if not re.search("[a-zA-Z]", block_size[0]):
            return int(block_size[0])
        else:
            return float(utils_misc.normalize_data_size(block_size[0],
                                                        order_magnitude="B"))
    else:
        test.error("Can not find the block size for the device."
                   " The output of command is: %s" % output)


def compare_block_size(test, session, params, expected_size, current_size):
    """
    Compare the current block size with the expected size.

    param expected_size: the expected size after block resize.
    param current_size: the size from guest after block resize.
    """
    accept_ratio = float(params.get("accept_ratio", 0))
    if (current_size <= expected_size and
            current_size >= expected_size * (1 - accept_ratio)):
        logging.info("Block Resizing Finished !!! \n"
                     "Current size %s is same as the expected %s",
                     current_size, expected_size)
        return True
    else:
        test.fail("Block size get from guest is not same as expected.\n"
                  "Reported: %s\nExpect: %s\n" % (current_size, expected_size))
    return


def get_drive_path_linux(test, session, params, data_image):
    """
    Get the drive id in linux guest.

    param data_image: data image name, like image1 or stg.
    param return: return drive path, like /dev/sda or /dev/sdb.
    """
    pattern = r"(serial|wwn)=(\w+)"
    match = re.search(pattern, params["blk_extra_params_%s" % data_image], re.M)
    if match:
        drive_id = match.group(2)
    else:
        test.fail("No available tag to get drive id")
    drive_path = utils_misc.get_linux_drive_path(session, drive_id)
    if not drive_path:
        test.error("Failed to get '%s' drive path" % data_image)
    return drive_path


def block_resize_enlarge(vm, session, params, device, block_size):
    """
    Enlarge the disk image of device to expected block_size.

    param device: enlarge device.
    param block_size: enlarge device to block_size.
    """
    logging.info("Enlarge disk size to %s in monitor"
                 % block_size, logging.info)
    vm.monitor.block_resize(device, block_size)
    if params.get("os_type") == "windows":
        drive.extend_shrink_disk(session, params["disk_index"],
                                 params["disk_letter"],
                                 operation="extend")


def block_resize_shrink(vm, session, params, device, old_disk_size, shrunk_size):
    """
    Shrink the disk image of device to expected block_size.

    param device: shrink device.
    param old_disk_size: the size before shrink.
    param shrunk_size: want to shrink size, after shrunk, the disk size
    should equal to "old_disk_size - shrunk_size".

    param return: return the block_size: "old_disk_size-shrunk_size".
    """
    if params.get("os_type") == "windows":
        shrunk_size = drive.extend_shrink_disk(session,
                                               params["disk_index"],
                                               params["disk_letter"],
                                               operation="shrink")
        shrunk_size = float(utils_misc.normalize_data_size("%sM" % shrunk_size,
                                                           order_magnitude="B"))
    block_size = old_disk_size - int(shrunk_size)
    logging.info("Shrink disk size to %s in monitor"
                 % block_size, logging.info)
    vm.monitor.block_resize(device, block_size)
    return block_size


def refresh_disk_after_resize(vm, session, params):
    """
    Rescan disk in windows or linux guest.
    In linux guest, after block_resize:
    need to rescan for virtio-scsi disk(no need reboot),
    need to reboot for virtio-blk disk(no need rescan).
    In windows guest, agter block_resize:
    need to rescan for both virtio-scsi and virtio-blk disk.
    """
    if params.get("guest_prepare_cmd"):
        session.cmd(params.get("guest_prepare_cmd"))
    if params.get("need_reboot", "no") == "yes":
        session = vm.reboot(session=session)
    if params.get("os_type") == "windows":
        drive.rescan_disk(session)


def block_resize_restore(vm, session, params, current_size, device,
                         original_size, accept_ratio):
    """
    Restore the disk image to the original size.

    After disk is shrunk, the disk size is less than the original size,
    especially for system disk, the lower size system disk may affect
    other tests running, so restore it to the original size.

    param device: restore device.
    param current_size: the disk current size.
    param original_size: the disk original_size.
    param accept_ratio: an accepted ratio.

    """
    if (current_size < original_size and
            current_size > original_size*(1-accept_ratio)):
        logging.info("Restore the disk to original size.")
        block_resize_enlarge(vm, session, params, device, original_size)


def iozone_test(test, session, iozone_cmd, disk_letter, iozone_timeout=360):
    """
    Run iozone_test on disk.

    param iozone_cmd: iozone command.
    param disk_letter: which disk will be test.
    param iozone_timeout: timeout for iozone running.

    """
    iozone_cmd = utils_misc.set_winutils_letter(session, iozone_cmd)
    logging.info("Running IOzone command on guest, timeout %ss"
                 % iozone_timeout, logging.info)
    status, results = session.cmd_status_output(cmd=iozone_cmd,
                                                timeout=iozone_timeout)
    if status != 0:
        test.fail("iozone test failed: %s" % results)


@error.context_aware
def run(test, params, env):
    """
    KVM block resize test:

    1) Start guest with data image and check the data image size.
    2) Enlarge(or Decrease) the data image and check it in guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    driver_name = params.get("driver_name")

    session = vm.wait_for_login(timeout=timeout)
    pattern = params.get("block_size_pattern")
    block_size_cmd = params["block_size_cmd"]
    accept_ratio = float(params.get("accept_ratio", 0))
    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    data_image_filename = storage.get_image_filename(data_image_params,
                                                     data_dir.get_data_dir())
    data_image_dev = vm.get_block({'file': data_image_filename})
    block_virtual_size = vm.monitor.get_block_virtual_size({'device': data_image_dev})
    disk_change_ratio = params.get("disk_change_ratio")
    block_resize_type = params["block_resize_type"]
    drive_path = ""

    if params.get("os_type") == 'linux':
        drive_path = get_drive_path_linux(test, session, params, data_image)
        block_size_cmd = params["block_size_cmd"].format(drive_path)

    if params.get("os_type") == "windows" and driver_name:
        utils_test.qemu.setup_win_driver_verifier(driver_name, vm, timeout)
        if params.get("format_disk", "no") == "yes":
            error.context("Format disk", logging.info)
            utils_misc.format_windows_disk(session, params["disk_index"],
                                           mountpoint=params["disk_letter"])

    error.context("Check image size before disk resize", logging.info)
    guest_disk_size = get_block_size(test, session, block_size_cmd, pattern)

    for type in block_resize_type.strip().split():
        if (guest_disk_size > block_virtual_size or
                guest_disk_size < block_virtual_size * (1-accept_ratio)):
            raise error.TestError("Image size from guest and image not match\n"
                                  "Block size get from guest: %s \n"
                                  "Image size get from image: %s \n"
                                  % (guest_disk_size, block_virtual_size))
        if type == "enlarge":
            enlarge_size = int(int(block_virtual_size) * float(disk_change_ratio))
            block_size = int(block_virtual_size) + enlarge_size
            block_resize_enlarge(vm, session, params, data_image_dev, block_size)
        elif type == "shrink":
            old_virtual_size = block_size
            shrunk_size = block_virtual_size * float(disk_change_ratio)
            block_size = block_resize_shrink(vm, session, params, data_image_dev,
                                             old_virtual_size, shrunk_size)
        refresh_disk_after_resize(session, params)
        new_disk_size = get_block_size(test, session, block_size_cmd, pattern)

        if not utils_misc.wait_for(lambda: compare_block_size
                                   (test, session, params, block_size,
                                    new_disk_size),
                                   20, 0, 1, "Block Resizing"):
            raise error.TestFail("Block size get from guest is not"
                                 "the same as expected \n"
                                 "Reported: %s\n"
                                 "Expect: %s\n" % (new_disk_size,
                                                   block_size))
        if params.get("iozone_test") == "yes":
            iozone_test(test, session, params.get("iozone_cmd"),
                        params["disk_letter"])
        block_resize_restore(vm, session, params, new_disk_size, data_image_dev,
                             block_virtual_size, accept_ratio)
    session.close()
