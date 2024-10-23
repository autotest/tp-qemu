"""Test booting with multi disks"""

import re

from virttest import env_process, error_context, utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number


@error_context.context_aware
def run(test, params, env):
    """
    Test booting with multi disks

    1) Boot the vm with multi disk.
    2) Check warning message for SeaBIOS booting.
    The limit of virtio disks accessible to SeaBIOS is 16 in both RHEL8
    and RHEL9. When the number of disks is greater than 16, we should see
    a WARNING in the seabios log.(Warning message like "WARNING - Unable to
    allocate resource at add_drive") No similar warning message in ovmf log.
    3) Login guest check the disk number.
    4) Execute IO operation on some disks.
    """

    def _prepare_images():
        image_name = params.get("stg_image_name", "images/%s")
        drive_format = params.get("stg_drive_format", "virtio")
        image_format = params.get("stg_image_format", "qcow2")

        for idx_ in range(stg_image_num):
            name = "stg%d" % idx_
            params["images"] = params["images"] + " " + name
            params["image_name_%s" % name] = image_name % name
            params["image_size_%s" % name] = image_size
            params["image_format_%s" % name] = image_format
            params["drive_format_%s" % name] = drive_format
            params["boot_drive_%s" % name] = "yes"
            params["blk_extra_params_%s" % name] = "serial=%s" % name

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        logger.debug("Check disk %s in guest", img)
        if os_type == "windows":
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(
                session, disk, image_size, os_type
            )[0]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path)

        logger.debug(cmd)
        session.cmd(cmd)

    logger = test.log
    stg_image_num = params.get_numeric("stg_image_num")
    os_type = params["os_type"]
    image_size = params.get("stg_image_size", "512M")
    guest_cmd = params["guest_cmd"]

    logger.info("Prepare images ...%s", params["stg_image_num"])
    _prepare_images()
    logger.info("Booting vm...")
    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    timeout = params.get_numeric("login_timeout", 360)

    logger.debug("Login in guest...")
    session = vm.wait_for_login(timeout=timeout)

    check_message = params.get("check_message")
    if check_message:
        logger.debug("Check warning message in BIOS log...")
        logs = vm.logsessions["seabios"].get_output()
        result = re.search(check_message, logs, re.S)
        result = "yes" if result else "no"
        expect_find = params.get("expect_find")
        if result != expect_find:
            test.fail("Get unexpected find %s %s" % (result, expect_find))

    logger.debug("Check disk number in guest...")
    check_num_cmd = params["check_num_cmd"]
    guest_cmd_output = session.cmd(check_num_cmd, timeout=60)
    guest_disk_num = int(guest_cmd_output.strip())
    expected_disk_number = stg_image_num + 1
    if guest_disk_num != expected_disk_number:
        test.fail(
            "Guest disk number is wrong,expected: %d actually: %d"
            % (guest_disk_num, expected_disk_number)
        )

    logger.debug("Check IO on guest disk...")
    for idx in range(params.get_numeric("check_disk_num", 3)):
        data_disk = "stg%d" % idx
        _check_disk_in_guest(data_disk)
