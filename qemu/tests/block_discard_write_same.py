"""sg_write_same command testing for discard feature"""

import os

from avocado.utils import process
from virttest import data_dir, env_process, error_context, storage
from virttest import data_dir as virttest_data_dir
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Execute sg_write_same command in guest for discard testing:
    1) Create image file on host .
    2) Boot guest with discard option on the image file as data disk
    3) Execute sg_write_same relevant operations in guest.
    4) Get sha1sum of the image file in guest.
    5) Cat content of image file
    6) Get sha1sum of the image file in host and should equal as step4.
    7) Using scsi_debug disk as data disk repeat step 1-5.


    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _run_sg_write_same(dev):
        file_name = "sg_write_same.sh"
        guest_dir = "/tmp/"
        deps_dir = virttest_data_dir.get_deps_dir() + "/thin-provision/"
        host_file = os.path.join(deps_dir, file_name)
        guest_file = guest_dir + file_name
        vm.copy_files_to(host_file, guest_dir)
        status, output = session.cmd_status_output("$SHELL " + guest_file + " " + dev)
        if status != 0:
            test.fail("run sg_write_same failed:" + output)
        test.log.debug(output)

    def _get_scsi_debug_disk(guest_session=None):
        """ "
        Get scsi debug disk on host or guest which created as scsi-block.
        """
        cmd = "lsblk -S -n -p|grep scsi_debug"

        if guest_session:
            status, output = guest_session.cmd_status_output(cmd)
        else:
            status, output = process.getstatusoutput(cmd)

        if status != 0:
            test.fail("Can not find scsi_debug disk")

        return output.split()[0]

    def _get_sha1sum(target, guest_session=None):
        cmd = "sha1sum %s | awk '{print $1}'" % target
        if guest_session:
            return guest_session.cmd_output(cmd).strip()
        return process.system_output(cmd, shell=True).decode()

    def _show_blocks_info(target):
        if scsi_debug == "yes":
            cmd = "cat /sys/bus/pseudo/drivers/scsi_debug/map"
        else:
            cmd = "qemu-img map --output=json " + target
        return process.system_output(cmd).decode()

    data_tag = params["data_tag"]
    vm_name = params["main_vm"]

    disk_serial = params["disk_serial"]
    scsi_debug = params.get("scsi_debug", "no")

    if scsi_debug == "yes":
        params["start_vm"] = "yes"
        disk_name = _get_scsi_debug_disk()
        params["image_name_%s" % data_tag] = disk_name
        # boot guest with scsi_debug disk
        env_process.preprocess_vm(test, params, env, vm_name)
    else:
        image_params = params.object_params(data_tag)
        disk_name = storage.get_image_filename(image_params, data_dir.get_data_dir())

    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Boot guest with disk '%s'" % disk_name, test.log.info)
    guest_disk_drive = get_linux_drive_path(session, disk_serial)
    if not guest_disk_drive:
        test.fail("Can not get data disk in guest.")

    error_context.context("Run sg_write_same cmd in guest", test.log.info)
    _run_sg_write_same(guest_disk_drive)

    error_context.context("Get sha1sum in guest", test.log.info)
    guest_sha1sum = _get_sha1sum(guest_disk_drive, session)

    error_context.context("Show blocks info", test.log.info)
    _show_blocks_info(disk_name)

    error_context.context("Get sha1sum on host", test.log.info)
    host_sha1sum = _get_sha1sum(disk_name)

    if guest_sha1sum != host_sha1sum:
        test.fail("Unmatched sha1sum %s:%s" % (guest_sha1sum, host_sha1sum))
