from avocado import fail_on
from avocado.utils import process

from virttest import utils_libguestfs

from provider import block_dirty_bitmap as block_bitmap
from provider.virt_storage.storage_admin import sp_admin
from provider import job_utils


@fail_on
def blockdev_create(vm, **options):
    timeout = int(options.pop("timeout", 360))
    vm.monitor.cmd("blockdev-create", options)
    job_utils.job_dismiss(vm, options["job-id"], timeout)


@fail_on
def blockdev_backup(vm, source, target, **extra_options):
    completed_event = "BLOCK_JOB_COMPLETED"
    if extra_options is None:
        extra_options = dict()
    extra_options["device"] = source
    extra_options["target"] = target
    extra_options["job-id"] = source
    extra_options.setdefault("sync", "full")
    timeout = int(extra_options.pop("timeout", 600))
    bitmap = extra_options.get("bitmap")
    if bitmap:
        info = block_bitmap.get_bitmap_by_name(vm, source, bitmap)
        assert info, "Bitmap '%s' not exists in device '%s'" % (bitmap, source)
        auto_disable_bitmap = extra_options.pop("auto_disable_bitmap", True)
        if auto_disable_bitmap and info.get("status") != "disabled":
            block_bitmap.block_dirty_bitmap_disable(vm, source, bitmap)
    vm.monitor.clear_event(completed_event)
    vm.monitor.blockdev_backup(extra_options)
    job_utils.wait_until_block_job_completed(vm, source, timeout)


@fail_on
def incremental_backup(vm, source, target, bitmap, **extra_options):
    """
    Do incremental backup with bitmap

    :param vm: VM object
    :param source: device ID or node-name
    :param target: target device node-name or ID
    :params bitmap: bitmap name on source device
    :param extra_options: extra arguments for blockdev-backup command
    """
    if not extra_options is None:
        extra_options = dict()
    extra_options["sync"] = "incremental"
    extra_options["bitmap"] = bitmap
    return blockdev_backup(vm, source, target, **extra_options)


@fail_on
def full_backup(vm, source, target, **extra_options):
    """ Do full backup for node"""
    if extra_options is None:
        extra_options = dict()
    extra_options["sync"] = "full"
    return blockdev_backup(vm, source, target, **extra_options)


def create_image_by_params(vm, params, image_name):
    """Create blockd device with vm by params"""
    image = sp_admin.volume_define_by_params(image_name, params)
    vm.verify_alive()
    image.hotplug(vm)
    return image


def format_storage_volume(img, filesystem, partition="mbr"):
    """
    format data disk with virt-format
    :param img: qemuImg object will be format
    :param filesystem:  filesystem want to make
    :param partition: partition type MBR or GPT
    """
    selinux_mode = process.getoutput("getenforce", shell=True)
    try:
        process.system("setenforce 0", shell=True)
        utils_libguestfs.virt_format(
            img.image_filename,
            filesystem=filesystem,
            image_format=img.image_format,
            partition="mbr")
    finally:
        process.system("setenforce %s" % selinux_mode, shell=True)
