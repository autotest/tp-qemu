import re

import six
from virttest import data_dir, error_context, utils_misc, utils_test
from virttest.qemu_capabilities import Flags
from virttest.qemu_storage import QemuImg


@error_context.context_aware
def run(test, params, env):
    """
    change a removable media:
    1) Boot VM with QMP/human monitor enabled.
    2) Connect to QMP/human monitor server.
    3) Check current block information.
    4) Insert some file to cdrom.
    5) Check current block information again.
    6) Mount cdrom to /mnt in guest to make it locked.
    7) Check current block information to make sure cdrom is locked.
    8) Change cdrom without force.
    9) Change a non-removable media.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def check_block_locked(block_name):
        blocks_info = monitor.info("block")

        if isinstance(blocks_info, six.string_types):
            lock_str = "locked=1"
            for block in blocks_info.splitlines():
                if block_name in block and lock_str in block:
                    return True
        else:
            for block in blocks_info:
                if vm.check_capability(Flags.BLOCKDEV):
                    condition = block["qdev"] == vm.devices.get_qdev_by_drive(
                        block_name
                    )
                else:
                    condition = block["device"] == block_name
                if condition and block["locked"]:
                    return True
        return False

    def change_block(cmd=None):
        try:
            output = monitor.send_args_cmd(cmd)
        except Exception as err:
            output = str(err)
        return output

    def get_qdev_by_filename(filename):
        for info_dict in vm.monitor.info("block"):
            if filename in str(info_dict):
                return info_dict["qdev"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    monitor = vm.get_monitors_by_type("qmp")
    if monitor:
        monitor = monitor[0]
    else:
        test.log.warning("qemu does not support qmp. Human monitor will be used.")
        monitor = vm.monitor
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cdrom = params.get("cdrom_cd1")
    cdrom = utils_misc.get_path(data_dir.get_data_dir(), cdrom)
    device_name = vm.get_block({"file": cdrom})
    if device_name is None:
        msg = "Unable to detect qemu block device for cdrom %s" % cdrom
        test.error(msg)
    orig_img_name = params.get("orig_img_name")
    change_insert_cmd = "change device=%s,target=%s" % (device_name, orig_img_name)
    if vm.check_capability(Flags.BLOCKDEV):
        qdev = vm.devices.get_qdev_by_drive(device_name)
        monitor.blockdev_open_tray(qdev, force=True)
        change_insert_cmd = "blockdev-change-medium id=%s,filename=%s" % (
            qdev,
            orig_img_name,
        )
    monitor.send_args_cmd(change_insert_cmd)
    test.log.info("Wait until device is ready")
    exists = utils_misc.wait_for(
        lambda: (orig_img_name in str(monitor.info("block"))), timeout=10, first=3
    )
    if not exists:
        msg = "Fail to insert device %s to guest" % orig_img_name
        test.fail(msg)

    if params.get("os_type") != "windows":
        error_context.context("lock cdrom in guest", test.log.info)
        lock_cmd = "eject -i on /dev/cdrom"
        session.cmd(lock_cmd)
        error_context.context("mount cdrom to make status to locked", test.log.info)
        cdroms = utils_misc.wait_for(
            lambda: (utils_test.get_readable_cdroms(params, session)), timeout=10
        )
        if not cdroms:
            test.fail("Not readable cdrom found in your guest")
        cdrom = cdroms[0]
        mount_cmd = params.get("cd_mount_cmd") % cdrom
        (status, output) = session.cmd_status_output(mount_cmd, timeout=360)
        if status:
            msg = "Unable to mount cdrom. "
            msg += "command: %s\nOutput: %s" % (mount_cmd, output)
            test.error(msg)

    else:
        error_context.context("lock cdrom in guest", test.log.info)
        tmp_dir = params.get("tmp_dir", "c:\\")
        eject_tool = utils_misc.get_path(data_dir.get_deps_dir(), "cdrom/eject.exe")
        vm.copy_files_to(eject_tool, tmp_dir)
        output = session.cmd("wmic cdrom get Drive", timeout=120)
        cd_vol = re.findall("[d-z]:", output, re.I)[0]
        lock_cmd = "%s\\eject.exe -i on %s" % (tmp_dir, cd_vol)
        (status, output) = session.cmd_status_output(lock_cmd)
        if status:
            msg = "Unable to lock cdrom. command: %s\n" % lock_cmd
            msg += "Output: %s" % output
            test.error(msg)

    if not check_block_locked(device_name):
        test.fail("device is not locked after mount it in guest.")

    error_context.context("Change media of cdrom", test.log.info)
    new_img_name = params.get("new_img_name")
    change_insert_cmd = "change device=%s,target=%s" % (device_name, new_img_name)
    if vm.check_capability(Flags.BLOCKDEV):
        change_insert_cmd = "blockdev-change-medium id=%s,filename=%s" % (
            vm.devices.get_qdev_by_drive(device_name),
            new_img_name,
        )
    output = change_block(change_insert_cmd)
    if not ("is locked" in output or "is not open" in output):
        msg = (
            "%s is not locked or is open "
            "after execute command %s "
            "command output: %s " % (device_name, change_insert_cmd, output)
        )
        test.fail(msg)

    blocks_info = monitor.info("block")
    if orig_img_name not in str(blocks_info):
        test.fail("Locked device %s is changed!" % orig_img_name)

    error_context.context("Change no-removable device", test.log.info)
    device_name = vm.get_block({"removable": False})
    if device_name is None:
        test.error("VM doesn't have any non-removable devices.")
    change_insert_cmd = "change device=%s,target=%s" % (device_name, new_img_name)
    if vm.check_capability(Flags.BLOCKDEV):
        sys_image = QemuImg(
            params, data_dir.get_data_dir(), params["images"].split()[0]
        )
        change_insert_cmd = "blockdev-change-medium id=%s,filename=%s" % (
            get_qdev_by_filename(sys_image.image_filename),
            new_img_name,
        )
    output = change_block(change_insert_cmd)
    if "is not removable" not in output:
        test.fail("Could remove non-removable device!")
    umount_cmd = params.get("cd_umount_cmd")
    if umount_cmd:
        session.cmd(umount_cmd, timeout=360, ignore_all_errors=True)
    session.close()
