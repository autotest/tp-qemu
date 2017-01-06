import logging

from avocado.core import exceptions

from virttest import error_context
from virttest import env_process
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest with virtio data disk
    2) Format the disk and copy file to it
    3) Stop the guest and boot up it again with the data disk set to readonly
    4) Try to copy file to the data disk
    5) Try to copy file from the data disk

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context(
        "TEST STEPS 1: Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context(
        "TEST STEPS 2: Format the disk and copy file to it", logging.info)
    os_type = params["os_type"]
    copy_cmd = params.get("copy_cmd", "copy %s %s")
    disk_idx = params.get("disk_index", 1)
    fs_type = params.get("fstype", "ntfs")
    drive_letter = params.get("drive_letter", "I:")
    disk_size = params.get("partition_size_data", "200M")
    src_file = utils_misc.set_winutils_letter(
        session, params["src_file"], label="WIN_UTILS")
    utils_misc.format_guest_disk(session, disk_idx, drive_letter,
                                 disk_size, fs_type, os_type)
    dst_file = params["dst_file"]
    session.cmd(copy_cmd % (src_file, dst_file))

    msg = "TEST STEPS 3: Stop the guest and boot up again with the data disk"
    msg += " set to readonly"
    error_context.context(msg, logging.info)
    session.close()
    vm.destroy()

    data_img = params.get("images").split()[-1]
    params["image_readonly_%s" % data_img] = "yes"
    params["force_create_image_%s" % data_img] = "no"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    error_context.context(
        "TEST STEPS 4: Write to the readonly disk expect:"
        "The media is write protected", logging.info)
    dst_file_readonly = params["dst_file_readonly"]
    o = session.cmd_output(copy_cmd % (src_file, dst_file_readonly))
    if not o.find("write protect"):
        raise exceptions.TestFail(
            "Write in readonly disk should failed\n. {}".format(o))

    error_context.context(
        "TEST STEPS 5: Try to read from the readonly disk", logging.info)
    s, o = session.cmd_status_output(copy_cmd % (dst_file, r"C:\\"))
    if s != 0:
        raise exceptions.TestFail("Read file failed\n. {}".format(o))

    session.close()
