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


def blockdev_backup_qmp_cmd(source, target, **extra_options):
    """Generate blockdev-backup command"""
    if not isinstance(extra_options, dict):
        extra_options = dict()
    arguments = {"device": source, "target": target, "job-id": source}
    arguments["sync"] = extra_options.get("sync", "full")
    arguments["speed"] = int(extra_options.get("speed", 0))
    arguments["compress"] = extra_options.get("compress", False)
    arguments["auto-finalize"] = extra_options.get("auto-finalize", True)
    arguments["auto-dismiss"] = extra_options.get("auto-dismiss", True)
    arguments["on-source-error"] = extra_options.get(
        "on-source-error", "report")
    arguments["on-target-error"] = extra_options.get(
        "on-target-error", "report")
    if "bitmap" in extra_options:
        arguments["bitmap"] = extra_options["bitmap"]
        if "bitmap-mode" in extra_options:
            arguments["bitmap-mode"] = extra_options["bitmap-mode"]
    if "filter-node-name" in extra_options:
        arguments["filter-node-name"] = extra_options["filter-node-name"]
    return "blockdev-backup", arguments


@fail_on
def blockdev_backup(vm, source, target, **extra_options):
    cmd, arguments = blockdev_backup_qmp_cmd(source, target, **extra_options)
    timeout = int(extra_options.pop("timeout", 600))
    if "bitmap" in arguments:
        info = block_bitmap.get_bitmap_by_name(vm, source, arguments["bitmap"])
        assert info, "Bitmap '%s' not exists in device '%s'" % (
            arguments["bitmap"], source)
        auto_disable_bitmap = extra_options.pop("auto_disable_bitmap", True)
        if auto_disable_bitmap and info.get("status") != "disabled":
            block_bitmap.block_dirty_bitmap_disable(
                vm, source, arguments["bitmap"])
    vm.monitor.cmd(cmd, arguments)
    job_utils.wait_until_block_job_completed(vm, source, timeout)


@fail_on
def blockdev_batch_backup(vm, source_lst, target_lst,
                          bitmap_lst, **extra_options):
    actions = []
    bitmap_add_cmd = "block-dirty-bitmap-add"
    timeout = int(extra_options.pop("timeout", 600))
    for idx, src in enumerate(source_lst):
        backup_cmd, arguments = blockdev_backup_qmp_cmd(
            src, target_lst[idx], **extra_options)
        actions.append({"type": backup_cmd, "data": arguments})
        bitmap_data = {"node": source_lst[idx], "name": bitmap_lst[idx]}
        granularity = extra_options.get("granularity")
        persistent = extra_options.get("persistent")
        if granularity is not None:
            bitmap_data["granularity"] = int(granularity)
        if persistent is not None:
            bitmap_data["persistent"] = persistent
        actions.append({"type": bitmap_add_cmd, "data": bitmap_data})
    arguments = {"actions": actions}
    vm.monitor.cmd("transaction", arguments)
    map(lambda job: job_utils.wait_until_block_job_completed(
        vm, job, timeout), source_lst)


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
    if extra_options is None:
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
