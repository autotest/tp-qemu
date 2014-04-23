import os
import re
import logging
from autotest.client import os_dep
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    Qemu discard support test:
    1) load scsi_debug module with lbpws=1
    2) boot guest with scsi_debug emulated disk as extra data disk
    3) rewrite the disk with /dev/zero in guest
    4) check block allocation bitmap in host
    5) format the disk with ext4 or xfs (with discard support filesystem)
       then mount it
    6) execute fstrim command for the mount point
    7) check block allocation bitmap updated in host

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_host_scsi_disk():
        """
        Get latest scsi disk which emulated by scsi_debug module.
        """
        scsi_disk_info = utils.system_output("lsscsi").splitlines()
        scsi_debug = [_ for _ in scsi_disk_info if 'scsi_debug' in _][-1]
        scsi_debug = scsi_debug.split()
        host_id = scsi_debug[0][1:-1]
        device_name = scsi_debug[-1]
        return (host_id, device_name)

    def get_guest_discard_disk(session):
        """"
        Get disk without partitions in guest.
        """
        list_disk_cmd = "ls /dev/[sh]d*|sed 's/[0-9]//p'|uniq -u"
        disk = session.cmd_output(list_disk_cmd).splitlines()[0]
        return disk

    def get_provisioning_mode(device, host_id):
        """
        Get disk provisioning_mode, value usually is 'writesame_16', depends
        on params for scsi_debug module.
        """
        device_name = os.path.basename(device)
        path = "/sys/block/%s/device/scsi_disk" % device_name
        path += "/%s/provisioning_mode" % host_id
        return utils.read_one_line(path).strip()

    def get_allocation_bitmap():
        """
        Get block allocation bitmap
        """
        path = "/sys/bus/pseudo/drivers/scsi_debug/map"
        try:
            return utils.read_one_line(path).strip()
        except IOError:
            logging.warn("block allocation bitmap not exists")
        return ""

    # destroy all vms to avoid emulated disk marked drity before start test
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)

    os_dep.command("lsscsi")
    host_id, disk_name = get_host_scsi_disk()
    provisioning_mode = get_provisioning_mode(disk_name, host_id)
    logging.info("Current provisioning_mode = '%s'", provisioning_mode)
    bitmap = get_allocation_bitmap()
    if bitmap:
        logging.debug("block allocation bitmap: %s" % bitmap)
        raise error.TestError("block allocation bitmap not empty before test.")

    # prepare params to boot vm with scsi_debug disk.
    vm_name = params["main_vm"]
    test_image = "scsi_debug"
    params["start_vm"] = "yes"
    params["image_name_%s" % test_image] = disk_name
    params["image_format_%s" % test_image] = "raw"
    params["image_raw_device_%s" % test_image] = "yes"
    params["force_create_image_%s" % test_image] = "no"
    params["images"] = " ".join([params["images"], test_image])

    error.context("boot guest with disk '%s'" % disk_name, logging.info)
    # boot guest with scsi_debug disk
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Fresh block allocation bitmap before test.", logging.info)
    device_name = get_guest_discard_disk(session)
    rewrite_disk_cmd = params["rewrite_disk_cmd"]
    rewrite_disk_cmd = rewrite_disk_cmd.replace("DISK", device_name)
    session.cmd(rewrite_disk_cmd, timeout=timeout, ignore_all_errors=True)

    bitmap_before_trim = get_allocation_bitmap()
    if not re.match(r"\d+-\d+", bitmap_before_trim):
        logging.debug("bitmap before test: %s" % bitmap_before_trim)
        raise error.TestFail("bitmap should be continuous before fstrim")

    format_disk_cmd = params["format_disk_cmd"]
    format_disk_cmd = format_disk_cmd.replace("DISK", device_name)
    error.context("format disk '%s' in guest" % device_name, logging.info)
    session.cmd(format_disk_cmd)

    error.context("mount disk with discard options '%s'" % device_name,
                  logging.info)
    mount_disk_cmd = params["mount_disk_cmd"]
    mount_disk_cmd = mount_disk_cmd.replace("DISK", device_name)
    session.cmd(mount_disk_cmd)

    error.context("execute fstrim in guest", logging.info)
    fstrim_cmd = params["fstrim_cmd"]
    session.cmd(fstrim_cmd, timeout=timeout)

    bitmap_after_trim = get_allocation_bitmap()
    if not re.match(r"\d+-\d+,.*\d+-\d+$", bitmap_after_trim):
        logging.debug("bitmap after test: %s" % bitmap_before_trim)
        raise error.TestFail("discard command doesn't issue"
                             "to scsi_debug disk, please report bug for qemu")
    if vm:
        vm.destroy()
