"""Blockdev aio=io_uring basic test"""

from virttest import utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.block_devices_plug import BlockDevicesPlug


def run(test, params, env):
    """
    Blockdev aio=io_uring basic test. It tests multiple scenarios:
    Boot,hotplug-unplug
    Boot steps:
        1) Boot VM disk with aio=io_uring
        2) Verify disk in guest
    Hotplug-unplug test steps:
        1) Boot VM
        2) Hotplug the disks with aio=io_uring
        3) Verify disks in guest
    """

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        os_type = params["os_type"]
        logger.debug("Check disk %s in guest", img)
        if os_type == "windows":
            img_size = params.get("image_size_%s" % img)
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            logger.info("Clean disk:%s", disk)
            utils_disk.clean_partition_windows(session, disk)
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path)

        session.cmd(cmd)

    def boot_test():
        for img in io_uring_images:
            _check_disk_in_guest(img)

    def hotplug_unplug_test():
        plug = BlockDevicesPlug(vm)
        for img in io_uring_images:
            plug.hotplug_devs_serial(img)
            _check_disk_in_guest(img)
            plug.unplug_devs_serial(img)

    logger = test.log

    io_uring_images = params["io_uring_images"].split()
    guest_cmd = params.get("guest_cmd")
    guest_operation = params.get("guest_operation")

    logger.debug("Ready boot VM...")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)

    locals_var = locals()
    if guest_operation:
        logger.debug("Execute guest operation %s", guest_operation)
        locals_var[guest_operation]()
