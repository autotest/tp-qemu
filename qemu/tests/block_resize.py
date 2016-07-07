import logging
import re

from autotest.client.shared import error

from virttest import utils_misc
from virttest import utils_test
from virttest import funcatexit
from virttest import storage
from virttest import data_dir


@error.context_aware
def run(test, params, env):
    """
    KVM block resize test:

    1) Start guest with data image and check the data image size.
    2) Enlarge(or Decrease) the data image and check it in guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def get_block_size(session, block_cmd, block_pattern):
        """
        Get block size inside guest.
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
            raise error.TestError("Can not find the block size for the"
                                  " deivce. The output of command"
                                  " is: %s" % output)

    def compare_block_size(session, block_cmd, block_pattern):
        """
        Compare the current block size with the expected size.
        """
        global current_size
        current_size = get_block_size(session,
                                      block_size_cmd, block_size_pattern)
        if (current_size <= block_size and
                current_size >= block_size * (1 - accept_ratio)):
            logging.info("Block Resizing Finished !!! \n"
                         "Current size %s is same as the expected %s",
                         current_size, block_size)
            return True
        return

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    if params.get("need_enable_verifier", "no") == "yes":
        error.context("Enable %s driver verifier"
                      % params["driver_name"], logging.info)
        try:
            session = utils_test.qemu.setup_win_driver_verifier(
                      session, params["driver_name"], vm, timeout)
            funcatexit.register(env, params.get("type"),
                                utils_test.qemu.clear_win_driver_verifier,
                                session, params["driver_name"], vm, timeout)
        except Exception, e:
            raise error.TestFail(e)

    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    data_image_size = data_image_params.get("image_size")
    data_image_size = float(utils_misc.normalize_data_size(data_image_size,
                            order_magnitude="B"))
    data_image_filename = storage.get_image_filename(data_image_params,
                                                     data_dir.get_data_dir())
    data_image_dev = vm.get_block({'file': data_image_filename})

    drive_path = ""
    if params.get("os_type") == 'linux':
        drive_id = params["blk_extra_params_%s" % data_image].split("=")[1]
        drive_path = utils_misc.get_linux_drive_path(session, drive_id)
        if not drive_path:
            raise error.TestError("Failed to get '%s' drive path"
                                  % data_image)

    block_size_cmd = params["block_size_cmd"].format(drive_path)
    block_size_pattern = params.get("block_size_pattern")
    need_reboot = params.get("need_reboot", "no") == "yes"
    accept_ratio = float(params.get("accept_ratio", 0))

    error.context("Check image size in guest", logging.info)
    block_size = get_block_size(session, block_size_cmd, block_size_pattern)
    if (block_size > data_image_size or
            block_size < data_image_size * (1 - accept_ratio)):
        raise error.TestError("Image size from guest and image not match"
                              "Block size get from guest: %s \n"
                              "Image size get from image: %s \n"
                              % (block_size, data_image_size))

    if params.get("guest_prepare_cmd"):
        session.cmd(params.get("guest_prepare_cmd"))

    if params.get("format_disk", "no") == "yes":
        error.context("Format disk", logging.info)
        utils_misc.format_windows_disk(session, params["disk_index"],
                                       mountpoint=params["disk_letter"])

    disk_update_cmd = params.get("disk_update_cmd")
    if disk_update_cmd:
        disk_update_cmd = disk_update_cmd.split("::")

    disk_rescan_cmd = params.get("disk_rescan_cmd")

    block_size = data_image_size
    disk_change_ratio = params["disk_change_ratio"]
    for index, ratio in enumerate(disk_change_ratio.strip().split()):
        old_block_size = block_size
        block_size = int(int(data_image_size) * float(ratio))

        if block_size == old_block_size:
            logging.warn("Block size is not changed in round %s."
                         " Just skip it" % index)
            continue

        if disk_update_cmd:
            if "DISK_CHANGE_SIZE" in disk_update_cmd[index]:
                disk_unit = params.get("disk_unit", "M")
                size = abs(block_size - old_block_size)
                change_size = utils_misc.normalize_data_size("%sB" % size,
                                                             disk_unit)
                disk_update_cmd[index] = re.sub("DISK_CHANGE_SIZE",
                                                change_size.split(".")[0],
                                                disk_update_cmd[index])

        # So far only virtio drivers support online auto block size change in
        # linux guest. So we need manully update the the disk or even reboot
        # guest to get the right block size after change it from monitor.

        # We need shrink the disk in guest first, than in monitor
        if block_size < old_block_size and disk_update_cmd:
            error.context("Shrink disk size to %s in guest"
                          % block_size, logging.info)
            session.cmd(disk_update_cmd[index])

        error.context("Change disk size to %s in monitor"
                      % block_size, logging.info)
        vm.monitor.block_resize(data_image_dev, block_size)

        if need_reboot:
            session = vm.reboot(session=session)
        elif disk_rescan_cmd:
            error.context("Rescan disk", logging.info)
            session.cmd(disk_rescan_cmd)

        # We need expand disk in monitor first than extend it in guest
        if block_size > old_block_size and disk_update_cmd:
            error.context("Extend disk to %s in guest"
                          % block_size, logging.info)
            session.cmd(disk_update_cmd[index])

        global current_size
        current_size = 0
        if not utils_misc.wait_for(lambda: compare_block_size
                                   (session, block_size_cmd,
                                    block_size_pattern),
                                   20, 0, 1, "Block Resizing"):
            raise error.TestFail("Block size get from guest is not"
                                 "the same as expected \n"
                                 "Reported: %s\n"
                                 "Expect: %s\n" % (current_size,
                                                   block_size))
