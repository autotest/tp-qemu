import os
import re
import logging

from autotest.client import os_dep
from autotest.client.shared import utils

from avocado.core import exceptions
from avocado.utils import process

from virttest import env_process
from virttest import error_context


def get_scsi_disk(session=None):
    """
    Get latest scsi disk which emulated by scsi_debug module.

    :param session: Guest session
    :return: Scsi id and the disk name
    """
    if not session:
        scsi_disk_info = process.system_output("lsscsi", shell=True).splitlines()
        scsi_debug = [_ for _ in scsi_disk_info if 'scsi_debug' in _][-1]
    else:
        scsi_disk_info = session.cmd_output('lsscsi').splitlines()
        scsi_debug = [_ for _ in scsi_disk_info][-1]
    scsi_debug = scsi_debug.split()
    scsi_id = scsi_debug[0][1:-1]
    device_name = scsi_debug[-1]
    return scsi_id, device_name


def get_provisioning_mode(pci_id, device, session=None):
    """
    Get disk provisioning_mode, value usually is 'writesame_16', depends
    on params for scsi_debug module.

    :param pci_id: Pci slot number
    :param device: The disk name
    :param session: Guest session
    :return:
    """
    device_name = os.path.basename(device)
    path = "/sys/block/{:s}/device/scsi_disk".format(device_name)
    path += "/{:s}/provisioning_mode".format(pci_id)
    try:
        if session is None:
            o = utils.read_one_line(path).strip()
            return o
        else:
            o = session.cmd_output("cat %s" % path)
            return re.search(r"(unmap)", o).group(1)
    except IOError:
        logging.error("Can't get the provisioning_mode"
                      ", output is: {}".format(o), logging.error)


def get_allocation_bitmap():
    """
    Get block allocation bitmap
    """
    path = "/sys/bus/pseudo/drivers/scsi_debug/map"
    try:
        bitmap = utils.read_one_line(path).strip()
        return bitmap
    except IOError:
        raise exceptions.TestError("block allocation bitmap doesn't exists")


def get_guest_discard_disk(session):
    """
    Get disk without partitions in guest.

    :param session: Guest session
    :return: Guest disk name
    """
    list_disk_cmd = "ls /dev/[shv]d*|sed 's/[0-9]//p'|uniq -u"
    disk = session.cmd_output(list_disk_cmd).splitlines()[0]
    return disk


@error_context.context_aware
def run(test, params, env):

    """
      'thin-provisioning' functions test using scsi_debug:
      1) load scsi_debug module (writesame mode:lbpws=1)or(unmap mode:lbpu=1)
      2) boot guest with scsi_debug emulated disk as extra data disk
      3) rewrite the disk with /dev/zero in guest
      4) check block allocation bitmap in host
      5) format the disk with ext4 or xfs (with discard support filesystem)
      6) execute fstrim command for the mount point
      7) check block allocation bitmap updated in host

      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    error_context.context(
        "TEST STEP 1: Load emulated scsi disk before test", logging.info)
    os_dep.command("lsscsi")
    host_id, disk_name = get_scsi_disk()
    provisioning_mode = get_provisioning_mode(host_id, disk_name)
    logging.info(
        "Scsi pci id and plot is: {:s} and disk name "
        "is: {:s}".format(host_id, disk_name))
    logging.info("Current provisioning_mode = {:s}", provisioning_mode)

    # Bitmap must be empty before test
    if get_allocation_bitmap():
        logging.debug("Block allocation bitmap: %s" % get_allocation_bitmap())
        raise exceptions.TestError(
            "Block allocation bitmap not empty before test.")

    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    params["image_name_stg"] = disk_name
    error_context.context(
        "TEST STEP 2: Boot guest with disk {:s}".format(disk_name), logging.info)
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    guest_device_name = get_guest_discard_disk(session)
    rewrite_disk_cmd = params["rewrite_disk_cmd"]
    rewrite_disk_cmd = rewrite_disk_cmd.replace("DISK", guest_device_name)
    error_context.context(
        "TEST STEP 3: Rewrite the disk in {:s}, "
        "using the command {:s}".format(
            guest_device_name, rewrite_disk_cmd), logging.info)
    session.cmd(rewrite_disk_cmd, timeout=timeout, ignore_all_errors=True)
    bitmap_before_trim = get_allocation_bitmap()
    error_context.context("TEST STEP 4: Check bitmap before test: {:s}".format(
        bitmap_before_trim), logging.info)
    if not re.match(r"\d+-\d+", bitmap_before_trim):
        raise exceptions.TestFail(
            "Bitmap should be continuous before fstrim, {}".format(
                bitmap_before_trim))

    format_disk_cmd = params["format_disk_cmd"]
    format_disk_cmd = format_disk_cmd.replace("DISK1", guest_device_name)
    error_context.context("TEST STEP 5: Format disk '{:s}' in guest".format(
        guest_device_name), logging.info)
    session.cmd(format_disk_cmd)

    mount_disk_cmd = params["mount_disk_cmd"]
    mount_disk_cmd = mount_disk_cmd.replace("DISK1", guest_device_name)
    session.cmd(mount_disk_cmd)

    error_context.context("TEST STEP 6: Execute fstrim in guest", logging.info)
    fstrim_cmd = params["fstrim_cmd"]
    o = session.cmd_output(fstrim_cmd, timeout=timeout)
    if params.get(
            "drive_format_stg") == "virtio":
        if not re.search(params["match_str"], o):
            raise exceptions.TestError(
                "Command output is wrong,should be: {}.".format(
                    params["match_str"]))

    bitmap_after_trim = get_allocation_bitmap()
    error_context.context("TEST STEP 7: Bitmap after test: {:s}".format(
        bitmap_after_trim), logging.info)
    if params.get("drive_format_stg") == "scsi-hd":
        if not re.match(r"\d+-\d+,.*\d+-\d+$", bitmap_after_trim):
            raise exceptions.TestFail("discard command doesn't issue"
                                      "to scsi_debug disk, please report "
                                      "bug for qemu")
    else:
        if bitmap_before_trim != bitmap_after_trim:
            raise exceptions.TestError(
                "The disk is virtio_blk, the map should "
                "be the same.")
