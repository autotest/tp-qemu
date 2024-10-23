import logging
import re

from avocado.utils import cpu
from virttest import error_context, utils_disk, utils_misc, utils_test

from provider.storage_benchmark import generate_instance

LOG_JOB = logging.getLogger("avocado.test")


def check_data_disks(test, params, env, vm, session):
    """
    Check guest data disks (except image1)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    :param vm: VM object
    :param session: VM session
    """

    def _get_mount_points():
        """Get data disk mount point(s)"""
        mount_points = []
        os_type = params["os_type"]
        if os_type == "linux":
            mounts = session.cmd_output_safe("cat /proc/mounts | grep /dev/")
            for img in image_list:
                size = params["image_size_%s" % img]
                img_param = params["blk_extra_params_%s" % img].split("=")[1]
                drive_path = utils_misc.get_linux_drive_path(session, img_param)
                if not drive_path:
                    test.error("Failed to get drive path of '%s'" % img)
                did = drive_path[5:]
                for mp in re.finditer(r"/dev/%s\d+\s+(\S+)\s+" % did, mounts):
                    mount_points.append(mp.group(1))
                else:
                    mp = utils_disk.configure_empty_linux_disk(session, did, size)
                    mount_points.extend(mp)
        elif os_type == "windows":
            size_record = []
            for img in image_list:
                size = params["image_size_%s" % img]
                if size in size_record:
                    continue
                size_record.append(size)
                disks = utils_disk.get_windows_disks_index(session, size)
                if not disks:
                    test.fail("Fail to list image %s" % img)
                if not utils_disk.update_windows_disk_attributes(session, disks):
                    test.fail("Failed to update windows disk attributes")
                for disk in disks:
                    d_letter = utils_disk.configure_empty_windows_disk(
                        session, disk, size
                    )
                if not d_letter:
                    test.fail("Fail to format disks")
                mount_points.extend(d_letter)
        else:
            test.cancel("Unsupported OS type '%s'" % os_type)
        return mount_points

    image_list = params.objects("images")[1:]
    len(image_list)

    error_context.context("Check data disks in monitor!", LOG_JOB.info)
    monitor_info_block = vm.monitor.info_block(False)
    blocks = monitor_info_block.keys()
    for image in image_list:
        drive = "drive_%s" % image
        if drive not in blocks:
            test.fail("%s is missing: %s" % (drive, blocks))

    error_context.context("Read and write data on data disks", LOG_JOB.info)
    iozone_test = generate_instance(params, vm, "iozone")
    iozone_cmd = params["iozone_cmd"]
    iozone_timeout = float(params.get("iozone_timeout", 1800))
    try:
        for mp in _get_mount_points():
            iozone_test.run(iozone_cmd % mp, iozone_timeout)
    finally:
        iozone_test.clean()


def verify_eim_status(test, params, session):
    error_context.context("verify eim status.", test.log.info)
    variant_name = params.get("diff_parameter")
    if variant_name == "eim_off" or variant_name == "eim_on":
        for key_words in params["check_key_words"].split(";"):
            output = session.cmd_output('journalctl -k | grep -i "%s"' % key_words)
        if not output:
            test.fail(
                'journalctl -k | grep -i "%s"'
                "from the systemd journal log." % key_words
            )
        test.log.debug(output)


def verify_x2apic_status(test, params, session):
    error_context.context("verify x2apic status.", test.log.info)
    variant_name = params.get("diff_parameter")
    if variant_name == "x2apic":
        for key_words in params["check_key_words"].split(";"):
            output = session.cmd_output('journalctl -k | grep -i "%s"' % key_words)
        if not output:
            test.fail(
                'journalctl -k | grep -i "%s"'
                "from the systemd journal log." % key_words
            )
        test.log.debug(output)


@error_context.context_aware
def run(test, params, env):
    """
    [seabios] seabios support IOMMU for virtio-blk
    [seabios] seabios support IOMMU for virtio-scsi
    [seabios] seabios support IOMMU for virtio-net

    this case will:
    1) Boot guest with virtio devices and iommu is on.
    2) Check 'info block'.
    3) Read and write data on data disks.
    4) Ping guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    if cpu.get_vendor() != "intel":
        test.cancel("This case only support Intel platform")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    check_data_disks(test, params, env, vm, session)
    verify_eim_status(test, params, session)
    verify_x2apic_status(test, params, session)
    session.close()

    error_context.context("Ping guest!", test.log.info)
    guest_ip = vm.get_address()
    status, output = utils_test.ping(guest_ip, count=10, timeout=20)
    if status:
        test.fail("Ping guest failed!")
    ratio = utils_test.get_loss_ratio(output)
    if ratio != 0:
        test.fail("Loss ratio is %s", ratio)

    error_context.context("Check kernel crash message!", test.log.info)
    vm.verify_kernel_crash()
