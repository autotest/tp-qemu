"""
Disk utilities function for managing disks and filesystems in guest environments.

This module contains a function related to disk write command execution on
different OS types.
"""

from virttest import utils_disk
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number


def execute_dd_write_test(
    test,
    params,
    vm,
    image,
    fstype,
    src_file=None,
    dst_dir=None,
    dd_options={},
    timeout=60,
):
    """
    Execute the dd write test on the disk image inside the guest.
    Note: The target disk image should be the uninitialized disk.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param vm: The VM object.
    :param image: The image name. e.g: stg0
    :param src_file: The source file for dd write testing.
                    e.g: /dev/null, /dev/zero, /dev/random, /dev/unrandom, /dev/xxx
    :param dst_dir: The destination directory for dd write testing.
    :param dd_options: The options for dd command.
    :param timeout: The timeout for dd.
    """

    if fstype not in ("ntfs", "xfs"):
        test.error("The fstype is not supported, only 'xfs' and 'ntfs' are")

    session = vm.wait_for_login()
    is_windows = params["os_type"] == "windows"
    image_params = params.object_params(image)
    image_size = image_params.get("image_size")

    disk = None
    try:
        if is_windows:
            # Configure the empty disk for windows guest
            disk = get_disk_props_by_serial_number(session, image, ["Index"])["Index"]
            utils_disk.update_windows_disk_attributes(session, disk)
            utils_disk.clean_partition_windows(session, disk)
            driver = utils_disk.configure_empty_windows_disk(
                session, disk, image_size, fstype=fstype
            )[0]

            # create the related destination dir for dd testing
            if dst_dir:
                dst_dir = f"{driver}:\\{dst_dir}"
            else:
                dst_dir = f"{driver}:\\{image}"
            session.cmd(f"mkdir {dst_dir}")
        else:
            # Configure the empty disk for linux guest
            disk = get_linux_drive_path(session, image)
            partition_name = disk.split("/")[2]
            utils_disk.create_filesyetem_linux(session, partition_name, fstype=fstype)

            # create the related destination dir for dd testing
            if not dst_dir:
                dst_dir = f"/var/tmp/{image}"
            session.cmd(f"mkdir -p {dst_dir}")

            utils_disk.mount(disk, dst_dir, fstype=fstype, session=session)

        # start to run dd command
        bs = dd_options.get("bs", "1M")
        count = dd_options.get("count", "100")
        oflag = dd_options.get("oflag", "direct")
        if is_windows:
            dd_if = src_file if src_file else "/dev/urandom"
            cmd = f"dd if={dd_if} of={dst_dir}\\test.dat bs={bs} count={count}"
        else:
            dd_if = src_file if src_file else "/dev/zero"
            cmd = (
                f"dd if={dd_if} "
                f"of={dst_dir}/test.img "
                f"bs={bs} "
                f"count={count} "
                f"oflag={oflag}"
            )

        for k, v in dd_options.items():
            if k not in ("bs", "count", "oflag"):
                cmd += f" {k}={v}"

        session.cmd(cmd, timeout)

    finally:
        # We need to try to clean up and roll back the environment finally.
        try:
            if disk:
                if not is_windows:
                    utils_disk.is_mount(disk, dst_dir, fstype=fstype, session=session)
                    utils_disk.umount(disk, dst_dir, fstype=fstype, session=session)
                    session.cmd(f"rm -rf {dst_dir}")
                    # Send only the disk ID
                    disk_id = disk.split("/")[-1]
                    utils_disk.clean_partition(session, disk_id, params["os_type"])
                else:
                    session.cmd(f'"RD /S /Q "{dst_dir}"')
                    utils_disk.clean_partition(session, disk, params["os_type"])
        except Exception as e:
            test.log.warning(str(e))
