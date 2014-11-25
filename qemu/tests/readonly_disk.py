import logging
from autotest.client.shared import error
from virttest import aexpect
from virttest import utils_misc
from virttest import env_process


@error.context_aware
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
    error.context("Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    vols = utils_misc.get_winutils_vol(session)
    if not vols:
        raise error.TestError("Can not find winutils in guest.")
    filen = 0
    error.context("Format the disk and copy file to it", logging.info)
    os_type = params["os_type"]
    copy_cmd = params.get("copy_cmd", "copy %s %s")
    disk_idx = params.get("disk_index", 1)
    fs_type = params.get("fstype", "ntfs")
    drive_letter = params.get("drive_letter", "I")
    disk_size = params.get("partition_size_data", "200M")
    src_file = params.get("src_file", "").replace("WIN_UTIL", vols)
    utils_misc.format_guest_disk(session, disk_idx, drive_letter,
                                 disk_size, fs_type, os_type)
    dst_file = drive_letter + ":\\" + str(filen)
    session.cmd(copy_cmd % (src_file, dst_file))
    filen += 1

    msg = "Stop the guest and boot up it again with the data disk"
    msg += " set to readonly"
    error.context(msg, logging.info)
    session.close()
    vm.destroy()
    data_img = params.get("images").split()[-1]
    params["image_readonly_%s" % data_img] = "yes"
    params["force_create_image_%s" % data_img] = "no"
    env_process.preprocess(test, params, env)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    try:
        error.context("Try to write to the readonly disk", logging.info)
        dst_file_readonly = drive_letter + ":\\" + str(filen)
        session.cmd(copy_cmd % (src_file, dst_file_readonly))
        raise error.TestFail("Write in readonly disk should failed.")
    except aexpect.ShellCmdError:
        error.context("Try to read from the readonly disk", logging.info)
        session.cmd(copy_cmd % (dst_file, "C:\\"))

    session.close()
