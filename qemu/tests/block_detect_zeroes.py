"""blockdev detect-zeroes option test"""

import time

from virttest import data_dir, storage, utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.block_devices_plug import BlockDevicesPlug


def run(test, params, env):
    """
    QEMU blockdev detect-zeroes option test

    1) Boot the vm with disk has detect-zeroes option
    For hotplug test
        2) Hot-unplug and hot-plug disk with detect-zeroes option.
    For resize test
        2) execute block_resize option on disk
    For boot test
        skip
    3) Format the disk and execute IO on it.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        nonlocal guest_cmd
        os_type = params["os_type"]
        pre_guest_cmd = params.get("pre_guest_cmd")
        post_guest_cmd = params.get("post_guest_cmd")
        logger.debug("Check disk %s in guest", img)
        if os_type == "windows":
            img_size = params.get("image_size_%s" % img)
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            guest_cmd = cmd.format(output_path)
        else:
            driver = get_linux_drive_path(session, img)
            if not driver:
                test.fail("Can not find disk by %s" % img)
            logger.debug(driver)
            if pre_guest_cmd:
                pre_guest_cmd = pre_guest_cmd.format(driver)
                logger.debug(pre_guest_cmd)
                session.cmd(pre_guest_cmd)
            if post_guest_cmd:
                post_guest_cmd = post_guest_cmd.format(driver)
            output_path = "/home/{}/test.dat".format(driver)
            guest_cmd = guest_cmd.format(output_path)

        logger.debug("Ready execute cmd: %s", guest_cmd)
        session.cmd(guest_cmd)
        if post_guest_cmd:
            logger.debug(post_guest_cmd)
            session.cmd(post_guest_cmd)

    def boot_test():
        _check_disk_in_guest(data_img)

    def hotplug_unplug_test():
        plug = BlockDevicesPlug(vm)
        plug.unplug_devs_serial(data_img)
        plug.hotplug_devs_serial(data_img)
        _check_disk_in_guest(data_img)

    def block_resize_test():
        image_params = params.object_params(data_img)
        image_size = params.get_numeric("new_image_size_stg1")
        image_filename = storage.get_image_filename(
            image_params, data_dir.get_data_dir()
        )
        image_dev = vm.get_block({"file": image_filename})
        if not image_dev:
            blocks_info = vm.monitor.human_monitor_cmd("info block")
            logger.debug(blocks_info)
            for block in blocks_info.splitlines():
                if image_filename in block:
                    image_dev = block.split(":")[0]
                    logger.debug("Find %s node:%s", image_filename, image_dev)
                    break
        if not image_dev:
            test.fail("Can not find dev by %s" % image_filename)
        args = (None, image_size, image_dev)

        vm.monitor.block_resize(*args)
        time.sleep(3)
        _check_disk_in_guest(data_img)

    logger = test.log
    guest_cmd = params["guest_cmd"]
    data_img = params["data_image"]
    guest_operation = params.get("guest_operation")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login()

    locals_var = locals()
    if guest_operation:
        logger.debug("Execute guest operation %s", guest_operation)
        locals_var[guest_operation]()

    vm.destroy()
