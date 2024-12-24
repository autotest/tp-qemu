"""
Disk utilities functions for managing disks and filesystems in guest environments.

This module contains functions related to disk detection, filesystem creation,
and command execution for various OS types.
"""

from virttest import utils_disk
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number


def get_disk_by_id(os_type, disk_id, session):
    """
    :param os_type: The VM Operating System.
    :param disk_id: The VM disk ID.
    :param session: The guest session.
    """
    if os_type == "windows":
        idx_info = get_disk_props_by_serial_number(session, disk_id, ["Index"])
        if idx_info:
            return idx_info["Index"]
    else:
        return get_linux_drive_path(session, disk_id)


def init_disk_by_id(
    mount_point="1",
    fstype=None,
    os_type="linux",
    disk_id="",
    img_size=None,
    session=None,
    tmp_dir="/var/tmp/test",
):
    """
    :param mount_point: It could receive the following values:
                        "0": No mounting needed.
                        "1": Mounting is done automatically.
                        "other": The user specifies the mount point.
    :param fstype: The kind of filesystem (ntfs or xfs).
    :param os_type: The VM Operating System.
    :param disk_id: The ID of the VM's disk.
    :param session: The guest session.
    """
    fstype = "ntfs" if os_type == "windows" else "xfs"
    disk = get_disk_by_id(os_type, disk_id, session)
    driver = format_disk_by_fstype(disk, fstype, img_size, session)
    if os_type == "linux" and mount_point == "1":
        mount_disk(disk, session, tmp_dir)
    return driver


def format_disk_by_fstype(disk, fstype, img_size, session):
    """
    :param disk: The disk to be formatted.
    :param fstype: The kind of filesystem (ntfs or xfs).
    :param img_size: The size of the image to be configured in Windows.
    :param session: The guest session.
    """
    if fstype == "xfs":
        cmd = "mkfs.xfs -f {0}"
        cmd = cmd.format(disk)
        session.cmd(cmd)
        return disk
    else:
        utils_disk.update_windows_disk_attributes(session, disk)
        utils_disk.clean_partition_windows(session, disk)
        return utils_disk.configure_empty_disk(session, disk, img_size, "windows")[0]


def mount_disk(disk, session, tmp_dir):
    """
    :param disk: The disk to be formatted.
    :param session: The guest session.
    :param tmp_dir: The temporal directory to be mounted.
    """
    cmd = f"mkdir -p {tmp_dir} && mount -t xfs {{0}} {tmp_dir}"
    cmd = cmd.format(disk)
    session.cmd(cmd)


def execute_dd_on_disk_by_id(params, disk_id, session, tmp_dir=None):
    """
    :param params: QEMU test object.
    :param disk_id: The disk ID.
    :param session: The guest session.
    :param tmp_dir: The temporal directory to be mounted.
    """
    if not tmp_dir:
        tmp_dir = f"/var/tmp/{disk_id}"
    os_type = params["os_type"]
    img_size = params.get(f"image_size_{disk_id}")
    driver = init_disk_by_id(
        os_type=os_type,
        disk_id=disk_id,
        img_size=img_size,
        session=session,
        tmp_dir=tmp_dir,
    )
    if os_type == "windows":
        cmd = "dd if=/dev/urandom of={}:\\test.dat bs=1M count=100"
        cmd.format(driver)
    else:
        cmd = f"dd if=/dev/zero of={tmp_dir}/test.img bs=1M count=100 oflag=direct"
    session.cmd(cmd)
    if os_type == "linux":
        session.cmd(f"umount {tmp_dir}")


def execute_cmd_on_disk_by_id(params, disk_id, session, cmd, tmp_dir=None):
    """
    :param params: QEMU test object.
    :param disk_id: The disk ID.
    :param session: The guest session.
    :param tmp_dir: The temporal directory to be mounted.
    """
    if not tmp_dir:
        tmp_dir = f"/var/tmp/{disk_id}"
    os_type = params["os_type"]
    img_size = params.get(f"image_size_{disk_id}")
    driver = init_disk_by_id(
        os_type=os_type,
        disk_id=disk_id,
        img_size=img_size,
        session=session,
        tmp_dir=tmp_dir,
    )
    if os_type == "windows":
        cmd.format(driver)
    session.cmd(cmd)
    if os_type == "linux":
        session.cmd(f"umount {tmp_dir}")
