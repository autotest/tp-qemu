import os
import re

from avocado.utils import genio, process
from avocado.utils import path as utils_path
from virttest import env_process, error_context, utils_disk, utils_misc


@error_context.context_aware
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
        scsi_disk_info = process.system_output("lsscsi").decode().splitlines()
        scsi_debug = [_ for _ in scsi_disk_info if "scsi_debug" in _][-1]
        scsi_debug = scsi_debug.split()
        host_id = scsi_debug[0][1:-1]
        device_name = scsi_debug[-1]
        return (host_id, device_name)

    def get_guest_discard_disk(session):
        """ "
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
        return genio.read_one_line(path).strip()

    def get_allocation_bitmap():
        """
        Get block allocation bitmap
        """
        path = "/sys/bus/pseudo/drivers/scsi_debug/map"
        try:
            return genio.read_one_line(path).strip()
        except IOError:
            test.log.warning("block allocation bitmap not exists")
        return ""

    def _check_disk_partitions_number():
        """Check the data disk partitions number."""
        disks = utils_disk.get_linux_disks(session, True)
        return len(re.findall(r"%s\d+" % device_name[5:], " ".join(disks))) == 1

    # destroy all vms to avoid emulated disk marked drity before start test
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)

    utils_path.find_command("lsscsi")
    host_id, disk_name = get_host_scsi_disk()
    provisioning_mode = get_provisioning_mode(disk_name, host_id)
    test.log.info("Current provisioning_mode = '%s'", provisioning_mode)
    bitmap = get_allocation_bitmap()
    if bitmap:
        test.log.debug("block allocation bitmap: %s", bitmap)
        test.error("block allocation bitmap not empty before test.")

    # prepare params to boot vm with scsi_debug disk.
    vm_name = params["main_vm"]
    test_image = "scsi_debug"
    params["start_vm"] = "yes"
    params["image_name_%s" % test_image] = disk_name
    params["image_format_%s" % test_image] = "raw"
    params["image_raw_device_%s" % test_image] = "yes"
    params["force_create_image_%s" % test_image] = "no"
    params["images"] = " ".join([params["images"], test_image])

    error_context.context("boot guest with disk '%s'" % disk_name, test.log.info)
    # boot guest with scsi_debug disk
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Fresh block allocation bitmap before test.", test.log.info)
    device_name = get_guest_discard_disk(session)
    rewrite_disk_cmd = params["rewrite_disk_cmd"]
    rewrite_disk_cmd = rewrite_disk_cmd.replace("DISK", device_name)
    session.cmd(rewrite_disk_cmd, timeout=timeout, ignore_all_errors=True)

    bitmap_before_trim = get_allocation_bitmap()
    if not re.match(r"\d+-\d+", bitmap_before_trim):
        test.log.debug("bitmap before test: %s", bitmap_before_trim)
        test.fail("bitmap should be continuous before fstrim")

    error_context.context(
        "Create partition on '%s' in guest" % device_name, test.log.info
    )
    session.cmd(params["create_partition_cmd"].replace("DISK", device_name))

    if not utils_misc.wait_for(_check_disk_partitions_number, 30, step=3.0):
        test.error("Failed to get a partition on %s." % device_name)

    error_context.context("format disk '%s' in guest" % device_name, test.log.info)
    session.cmd(params["format_disk_cmd"].replace("DISK", device_name))

    error_context.context(
        "mount disk with discard options '%s'" % device_name, test.log.info
    )
    mount_disk_cmd = params["mount_disk_cmd"]
    mount_disk_cmd = mount_disk_cmd.replace("DISK", device_name)
    session.cmd(mount_disk_cmd)

    error_context.context("execute fstrim in guest", test.log.info)
    fstrim_cmd = params["fstrim_cmd"]
    session.cmd(fstrim_cmd, timeout=timeout)

    bitmap_after_trim = get_allocation_bitmap()
    if not re.match(r"\d+-\d+,.*\d+-\d+$", bitmap_after_trim):
        test.log.debug("bitmap after test: %s", bitmap_before_trim)
        test.fail(
            "discard command doesn't issue"
            "to scsi_debug disk, please report bug for qemu"
        )
    if vm:
        vm.destroy()
