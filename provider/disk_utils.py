"""
Disk utilities function for managing disks and filesystems in guest environments.

This module contains a function related to disk I/O test command execution on
different OS types.
"""

import logging

from virttest import utils_disk
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

LOG_JOB = logging.getLogger("avocado.test")


def get_disk_by_serial(os_type, serial, session):
    """
    This function provides the disk ID reference.
    It will vary based on the OS (ID or path).

    :param os_type: The VM Operating System.
    :param serial: The disk serial ID.
    :param session: The guest session.
    """
    if os_type == "windows":
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
    else:
        return get_linux_drive_path(session, serial)


def init_disk_by_id(
    params,
    vm,
    did,
    image_name,
    dst_dir=None,
    fstype=None,
):
    """
    Initializes the disk in the guest based on the received device ID.
    By initialize, it means obtain the reference of the disk (ID or path) and
    later in Linux systems, create the filesystem + mounting or formatting the
    disk in Windows ones.

    :param params: Dictionary with the test parameters.
    :param vm: The VM object.
    :param did: The ID of the VM's disk.
    :param image_name: The image name. e.g: stg0
    :param dst_dir: The destination directory for mounting.
    :param fstype: The kind of filesystem (ntfs or xfs).
    :returns: mount point for windows or folder name in Linux
    """
    session = vm.wait_for_login()
    is_windows = params.get("os_type") == "windows"
    image_params = params.object_params(image_name)
    img_size = image_params.get("image_size")

    if fstype is None:
        fstype = "ntfs" if is_windows else "xfs"

    if not dst_dir and not is_windows:
        dst_dir = f"/mnt/{image_name}"
        session.cmd(f"mkdir -p {dst_dir}")

    if is_windows:
        utils_disk.update_windows_disk_attributes(session, did)
        utils_disk.clean_partition_windows(session, did)
        return utils_disk.configure_empty_disk(session, did, img_size, "windows")[0]
    else:
        # Send only the disk ID
        disk_id = did.split("/")[-1]
        utils_disk.create_filesyetem_linux(session, disk_id, fstype)
        if utils_disk.mount(did, dst_dir, fstype, session=session):
            return dst_dir


def execute_io_test(
    params,
    vm,
    image,
    serial,
    fstype=None,
    dst_dir=None,
    io_command=None,
    clean=True,
    ignore_all_errors=False,
    timeout=60,
):
    """
    Execute the I/O write test on the disk image inside the guest.
    Note: The target disk image should be the uninitialized disk.

    :param params: Dictionary with the test parameters.
    :param vm: The VM object.
    :param image: The image name. e.g: stg0
    :param serial: The serial number of the disk
    :param dst_dir: The destination directory for I/O write testing.
    :param io_command: The command for I/O test.
    :param clean: If True, cleans the environment
    :param ignore_all_errors: Checks the errors of the I/O command
    :param timeout: The timeout for the I/O command.
    """
    session = vm.wait_for_login()
    os_type = params.get("os_type")
    is_windows = True if os_type == "windows" else False

    did = get_disk_by_serial(os_type, serial, session)
    mount_point = init_disk_by_id(params, vm, did, image, dst_dir, fstype)

    log_message = f"The did: {did} and the mount point: {mount_point}"
    LOG_JOB.debug(log_message)

    try:
        # Start to run I/O command
        if io_command:
            io_cmd = io_command % mount_point
            session.cmd(io_cmd, timeout, ignore_all_errors=ignore_all_errors)
    finally:
        if clean:
            # We need to try to clean up and roll back the environment finally.
            if not is_windows:
                if utils_disk.is_mount(
                    did, mount_point, fstype=fstype, session=session
                ):
                    utils_disk.umount(did, mount_point, fstype=fstype, session=session)
                    session.cmd(f"rm -rf {mount_point}")
                    # Send only the disk ID
                    disk_id = did.split("/")[-1]
                    utils_disk.clean_partition(session, disk_id, os_type)
            else:
                utils_disk.clean_partition(session, did, os_type)
