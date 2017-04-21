import re
import os
import logging

from autotest.client.shared import error
from autotest.client.shared import utils
from autotest.client import os_dep
from virttest import env_process
from avocado.utils import process
from avocado.core import exceptions


def get_scsi_disk(session=None):
    """
    Get latest scsi disk which emulated by scsi_debug module.

    :param session: Guest session
    :return: Scsi id and the disk name
    """
    if session is None:
        scsi_disk_info = process.system_output("lsscsi").splitlines()
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
            return utils.read_one_line(path).strip()
        else:
            session.cmd("read < {:s}".format(path))
            return session.cmd_output("echo $REPLY")
    except IOError:
        logging.error("Can't get the provisioning_mode", logging.error)


def get_allocation_bitmap():
    """
    Get block allocation bitmap
    """
    path = "/sys/bus/pseudo/drivers/scsi_debug/map"
    try:
        bitmap = utils.read_one_line(path).strip()
        if not re.match(r"\d+-\d+", bitmap):
            raise exceptions.TestFail("Bitmap should be continuous before fstrim, {}".format(bitmap))
        return utils.read_one_line(path).strip()
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


def destroy_vm(env):
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)


@error.context_aware
def run(test, params, env):
    """
      'thin-provisioning' functions test using scsi_debug:
      1) Boot up the guest
      2) Create a file in the guest disk
      3) Get the Bitmap and check it
      4) Format the disk
      5) Get the Bitmap and check it

      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    # Destroy all vms to avoid emulated disk marked drity before start test
    destroy_vm(env)
    os_dep.command("lsscsi")
    host_id, disk_name = get_scsi_disk()
    provisioning_mode = get_provisioning_mode(host_id, disk_name)
    logging.info("Scsi pci id and plot is: {:s} and disk name is: {:s}".format(host_id, disk_name))
    logging.info("Current provisioning_mode = {:s}", provisioning_mode)

    # Bitmap must be empty before test
    if get_allocation_bitmap():
        logging.debug("Block allocation bitmap: %s" % get_allocation_bitmap())
        raise error.TestError("Block allocation bitmap not empty before test.")

    vm_name = params["main_vm"]
    test_image = params.get("test_image")
    params["start_vm"] = "yes"
    params["image_name_%s" % test_image] = disk_name
    params["image_format_%s" % test_image] = "raw"
    params["image_raw_device_%s" % test_image] = "yes"
    params["force_create_image_%s" % test_image] = "no"
    params["drv_extra_params_scsi_debug"] = "discard=on"
    params["images"] = " ".join([params["images"], test_image])

    error.context("TEST STEP 1: Boot guest with disk {:s}".format(disk_name), logging.info)
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    guest_device_name = get_guest_discard_disk(session)
    rewrite_disk_cmd = params["rewrite_disk_cmd"]
    rewrite_disk_cmd = rewrite_disk_cmd.replace("DISK", guest_device_name)
    error.context("TEST STEP 2: Create a file in {:s}, using the command {:s}".format(guest_device_name,
                                                                                      rewrite_disk_cmd), logging.info)
    session.cmd(rewrite_disk_cmd, timeout=timeout, ignore_all_errors=True)
    bitmap_before_trim = get_allocation_bitmap()
    error.context("TEST STEP 3: Bitmap before test: {:s}".format(bitmap_before_trim), logging.info)

    format_disk_cmd = params["format_disk_cmd"]
    format_disk_cmd = format_disk_cmd.replace("DISK1", guest_device_name)
    error.context("TEST STEP 3: Format disk '{:s}' in guest".format(guest_device_name), logging.info)
    session.cmd(format_disk_cmd)

    error.context("TEST STEP 4: Mount disk with discard options {:s}".format(guest_device_name),
                  logging.info)
    mount_disk_cmd = params["mount_disk_cmd"]
    mount_disk_cmd = mount_disk_cmd.replace("DISK1", guest_device_name)
    session.cmd(mount_disk_cmd)

    error.context("TEST STEP 5: Execute fstrim in guest", logging.info)
    fstrim_cmd = params["fstrim_cmd"]
    o = session.cmd_output(fstrim_cmd, timeout=timeout)
    if not params.get("drive_format_{:s}".format(test_image), None) == "scsi-hd":
        if not re.search(params["match_str"], o):
            raise exceptions.TestError("Commond output is wrong,please check.", logging.error)

    bitmap_after_trim = get_allocation_bitmap()
    error.context("TEST STEP 6: Bitmap after test: {:s}".format(bitmap_after_trim), logging.info)
    if params.get("drive_format_{:s}".format(test_image), None) == "scsi-hd":
        if not re.match(r"\d+-\d+,.*\d+-\d+$", bitmap_after_trim):
            raise exceptions.TestFail("discard command doesn't issue"
                                      "to scsi_debug disk, please report bug for qemu")
    else:
        if bitmap_before_trim != bitmap_after_trim:
            raise exceptions.TestError("The disk is virtio_blk, the map should be the same.", logging.error)
    if vm:
        vm.destroy()
