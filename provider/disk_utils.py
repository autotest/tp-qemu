"""
Disk utilities functions for managing disks and filesystems in guest environments.

This module contains functions related to disk detection, filesystem creation,
and command execution for various OS types.
"""

import os

from virttest import utils_disk
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number


def get_disk_reference_by_id(os_type, disk_id, session):
    """
    This function provides the disk ID reference.
    It will vary based on the OS (ID or path).

    :param os_type: The VM Operating System.
    :param disk_id: The VM disk ID defined in the test cfg.
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
    test=None,
):
    """
    Initializes the disk in the guest based on the received device ID.
    By initialize, it means obtain the reference of the disk (ID or path) and
    later in Linux systems, create the filesystem + mounting or formatting the
    disk in Windows ones.

    :param mount_point: It could receive the following values:
                        "0": No mounting needed.
                        "1": Mounting is done automatically.
                        "other": The user specifies the mount point.
    :param fstype: The kind of filesystem (ntfs or xfs).
    :param os_type: The VM Operating System.
    :param disk_id: The ID of the VM's disk defined in the test cfg.
    :param session: The guest session.
    """
    if fstype not in ["ntfs", "xfs"]:
        test.error("The fstype is not supported, only 'xfs' and 'ntfs' are")
    disk = get_disk_reference_by_id(os_type, disk_id, session)
    if os_type == "linux" and mount_point == "1":
        partition_name = disk.split("/")[2]
        utils_disk.create_filesyetem_linux(session, partition_name, fstype="xfs")
        utils_disk.mount(disk, tmp_dir, fstype="xfs", session=session)
        driver = disk  # For Linux, return the disk itself
    else:
        driver = formats_disk(disk, img_size, session)
    return driver


def formats_disk(disk, img_size, session):
    """
    This function cleans, creates and formats the disk partition of a Windows
    guest.

    :param disk: The disk to be formatted.
    :param img_size: The size of the image to be configured in Windows.
    :param session: the Windows guest session
    """
    utils_disk.update_windows_disk_attributes(session, disk)
    utils_disk.clean_partition_windows(session, disk)
    return utils_disk.configure_empty_disk(session, disk, img_size, "windows")[0]


def execute_dd_on_disk_by_id(params, disk_id, session, tmp_dir=None, test=None):
    """
    This function executes a dd command on the received disk,
    which is previously initialized.

    :param params: QEMU test object.
    :param disk_id: The disk ID defined in the test cfg.
    :param session: The guest session.
    :param tmp_dir: The temporal directory where the image will be mounted.
    """
    os_type = params["os_type"]
    if not tmp_dir:
        if os_type == "windows":
            tmp_dir = os.path.join("C:\\", disk_id)
        else:
            tmp_dir = os.path.join("/var/tmp/", disk_id)

    if not os.path.isdir(tmp_dir):
        session.cmd(f"mkdir {tmp_dir}")

    img_size = params.get(f"image_size_{disk_id}")
    fstype = params["fstype"]
    driver = init_disk_by_id(
        fstype=fstype,
        os_type=os_type,
        disk_id=disk_id,
        img_size=img_size,
        session=session,
        tmp_dir=tmp_dir,
        test=test,
    )
    if os_type == "windows":
        cmd = "dd if=/dev/urandom of={}:\\test.dat bs=1M count=100"
        cmd.format(driver)
    else:
        cmd = f"dd if=/dev/zero of={tmp_dir}/test.img bs=1M count=100 oflag=direct"
    session.cmd(cmd)
    if os_type == "linux":
        session.cmd(f"umount {tmp_dir}")
