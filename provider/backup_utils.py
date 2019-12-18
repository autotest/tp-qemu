from avocado import fail_on
from avocado.utils import process

from virttest import utils_libguestfs
from virttest import utils_numeric
from virttest import utils_misc

from provider import block_dirty_bitmap as block_bitmap
from provider.virt_storage.storage_admin import sp_admin
from provider import job_utils


@fail_on
def generate_tempfile(vm, root_dir, filename, size="10M", timeout=720):
    """Generate temp data file in VM"""
    session = vm.wait_for_login()
    if vm.params["os_type"] == "windows":
        file_path = "%s\\%s" % (root_dir, filename)
        mk_file_cmd = "fsutil file createnew %s %s" % (file_path, size)
        md5_cmd = "certutil -hashfile %s MD5 > %s.md5" % (file_path, file_path)
    else:
        file_path = "%s/%s" % (root_dir, filename)
        size_str = int(
            utils_numeric.normalize_data_size(
                size,
                order_magnitude="K",
                factor=1024))
        count = size_str // 4
        mk_file_cmd = "dd if=/dev/urandom of=%s bs=4k count=%s oflag=direct" % (
            file_path, count)
        md5_cmd = "md5sum %s > %s.md5 && sync" % (file_path, file_path)
    try:
        session.cmd(mk_file_cmd, timeout=timeout)
        session.cmd(md5_cmd, timeout=timeout)
    finally:
        session.close()


@fail_on
def verify_file_md5(vm, root_dir, filename, timeout=720):
    if vm.params["os_type"] == "windows":
        file_path = "%s\\%s" % (root_dir, filename)
        md5_cmd = "certutil -hashfile %s MD5" % file_path
        cat_cmd = "type %s.md5" % file_path
    else:
        file_path = "%s/%s" % (root_dir, filename)
        md5_cmd = "md5sum %s" % file_path
        cat_cmd = "cat %s.md5" % file_path

    session = vm.wait_for_login()
    try:
        status1, output1 = session.cmd_status_output(md5_cmd, timeout=timeout)
        now = output1.strip()
        assert status1 == 0, "Get file ('%s') MD5 with error: %s" % (
            filename, output1)
        status2, output2 = session.cmd_status_output(cat_cmd, timeout=timeout)
        saved = output2.strip()
        assert status2 == 0, "Read file ('%s') MD5 file with error: %s" % (
            filename, output2)
        assert now == saved, "File's ('%s') MD5 is mismatch! (%s, %s)" % (
            filename, now, saved)
    finally:
        session.close()


@fail_on
def blockdev_create(vm, **options):
    timeout = int(options.pop("timeout", 360))
    vm.monitor.cmd("blockdev-create", options)
    job_utils.job_dismiss(vm, options["job-id"], timeout)


def blockdev_backup_qmp_cmd(source, target, **extra_options):
    """Generate blockdev-backup command"""
    if not isinstance(extra_options, dict):
        extra_options = dict()
    random_id = utils_misc.generate_random_string(4)
    job_id = "%s_%s" % (source, random_id)
    arguments = {"device": source, "target": target, "job-id": job_id}
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
    job_id = arguments.get("job-id", source)
    job_utils.wait_until_block_job_completed(vm, job_id, timeout)


@fail_on
def blockdev_batch_backup(vm, source_lst, target_lst,
                          bitmap_lst, **extra_options):
    actions = []
    bitmap_add_cmd = "block-dirty-bitmap-add"
    timeout = int(extra_options.pop("timeout", 600))
    jobs_id = []
    for idx, src in enumerate(source_lst):
        backup_cmd, arguments = blockdev_backup_qmp_cmd(
            src, target_lst[idx], **extra_options)
        job_id = arguments.get("job-id", src)
        jobs_id.append(job_id)
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
    list(map(lambda x: job_utils.wait_until_block_job_completed(vm, x, timeout), jobs_id))


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
