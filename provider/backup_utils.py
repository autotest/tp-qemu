import json
import math
import random
import re

from avocado import fail_on
from avocado.utils import process
from virttest import (
    data_dir,
    qemu_storage,
    utils_disk,
    utils_libguestfs,
    utils_misc,
    utils_numeric,
    utils_version,
)

from provider import block_dirty_bitmap as block_bitmap
from provider import job_utils
from provider.virt_storage.storage_admin import sp_admin

BACKING_MASK_PROTOCOL_VERSION_SCOPE = "[9.0.0, )"


def set_default_block_job_options(obj, arguments):
    """
    Set the default options only when they are not set by users
    """
    options = {
        "backing-mask-protocol": (BACKING_MASK_PROTOCOL_VERSION_SCOPE, True),
    }

    version = None
    if hasattr(obj, "devices"):
        version = obj.devices.qemu_version
    elif hasattr(obj, "qsd_version"):
        version = obj.qsd_version

    for key, (scope, value) in options.items():
        if version in utils_version.VersionInterval(scope):
            arguments[key] = arguments.get(key, value)


def generate_log2_value(start, end, step=1, blacklist=None):
    if blacklist is None:
        blacklist = list()
    outlist = list(filter(lambda x: math.log2(x).is_integer(), range(start, end, step)))
    pool = set(outlist) - set(blacklist)
    return random.choice(list(pool))


def generate_random_cluster_size(blacklist):
    """
    generate valid value for cluster size
    :param blacklist: black list of cluster_size value
    :return: int type valid cluster size
    """
    return generate_log2_value(512, 2097152, 1, blacklist)


def copy_out_dict_if_exists(params_in, keys):
    """
    get sub-dict from by keys

    :param params_in: original dict
    :param keys: list or dict, key list or key with default value
    :return dict: sub-dict of params_in
    """
    params_out = dict()
    if not isinstance(params_in, dict):
        params_in = dict()
    if isinstance(keys, list):
        keys = params_in.fromkeys(keys, None)
    for key, default in keys.items():
        val = params_in.get(key, default)
        if val is None:
            continue
        if key in ["speed", "granularity", "buf-size", "timeout"]:
            params_out[key] = int(val)
            continue
        if key in [
            "auto-finalize",
            "auto-dismiss",
            "unmap",
            "persistent",
            "backing-mask-protocol",
        ]:
            if val in ["yes", "true", "on", True]:
                params_out[key] = True
                continue
            elif val in ["no", "false", "off", False]:
                params_out[key] = False
                continue
        params_out[key] = val
    return params_out


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
        count = int(
            utils_numeric.normalize_data_size(size, order_magnitude="M", factor=1024)
        )
        dd_cmd = vm.params.get(
            "dd_cmd", "dd if=/dev/urandom of=%s bs=1M count=%s oflag=direct"
        )
        mk_file_cmd = dd_cmd % (file_path, count)
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
        assert status1 == 0, "Get file ('%s') MD5 with error: %s" % (filename, output1)
        status2, output2 = session.cmd_status_output(cat_cmd, timeout=timeout)
        saved = output2.strip()
        assert status2 == 0, "Read file ('%s') MD5 file with error: %s" % (
            filename,
            output2,
        )
        assert now == saved, "File's ('%s') MD5 is mismatch! (%s, %s)" % (
            filename,
            now,
            saved,
        )
    finally:
        session.close()


def blockdev_snapshot_qmp_cmd(source, target, **extra_options):
    options = ["node", "overlay"]
    arguments = copy_out_dict_if_exists(extra_options, options)
    arguments["node"] = source
    arguments["overlay"] = target
    return "blockdev-snapshot", arguments


def blockdev_mirror_qmp_cmd(source, target, **extra_options):
    random_id = utils_misc.generate_random_string(4)
    job_id = "%s_%s" % (source, random_id)
    options = [
        "format",
        "node-name",
        "replaces",
        "sync",
        "mode",
        "granularity",
        "speed",
        "copy-mode",
        "buf-size",
        "on-source-error",
        "on-target-error",
        "auto-finalize",
        "auto-dismiss",
        "filter-node-name",
        "unmap",
    ]
    arguments = copy_out_dict_if_exists(extra_options, options)
    arguments["device"] = source
    arguments["target"] = target
    arguments["job-id"] = job_id
    return "blockdev-mirror", arguments


def block_commit_qmp_cmd(device, **extra_options):
    random_id = utils_misc.generate_random_string(4)
    job_id = "%s_%s" % (device, random_id)
    options = [
        "base-node",
        "base",
        "top-node",
        "top",
        "backing-file",
        "speed",
        "on-error",
        "filter-node-name",
        "auto-finalize",
        "auto-dismiss",
        "backing-mask-protocol",
    ]
    arguments = copy_out_dict_if_exists(extra_options, options)
    arguments["device"] = device
    arguments["job-id"] = job_id
    return "block-commit", arguments


def blockdev_stream_qmp_cmd(device, **extra_options):
    if not isinstance(extra_options, dict):
        extra_options = dict()
    random_id = utils_misc.generate_random_string(4)
    job_id = "%s_%s" % (device, random_id)
    arguments = {"device": device, "job-id": job_id}
    # TODO: we may have to sync the block-stream options with libvirt
    options = [
        "speed",
        "base",
        "base-node",
        "snapshot-file",
        "filter-node-name",
        "on-error",
        "backing-file",
        "auto-dismiss",
        "auto-finalize",
        "backing-mask-protocol",
    ]
    args = copy_out_dict_if_exists(extra_options, options)
    if args:
        arguments.update(args)
    return "block-stream", arguments


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
    arguments["on-source-error"] = extra_options.get("on-source-error", "report")
    arguments["on-target-error"] = extra_options.get("on-target-error", "report")
    if "bitmap" in extra_options:
        arguments["bitmap"] = extra_options["bitmap"]
        if "bitmap-mode" in extra_options:
            arguments["bitmap-mode"] = extra_options["bitmap-mode"]
    if "filter-node-name" in extra_options:
        arguments["filter-node-name"] = extra_options["filter-node-name"]
    x_perf_ops = ["use-copy-range", "max-workers", "max-chunk"]
    if any(item in extra_options for item in x_perf_ops):
        arguments["x-perf"] = {
            x: extra_options[x] for x in x_perf_ops if x in extra_options
        }
    return "blockdev-backup", arguments


@fail_on
def blockdev_create(vm, **options):
    timeout = int(options.pop("timeout", 360))
    vm.monitor.cmd("blockdev-create", options)
    job_utils.job_dismiss(vm, options["job-id"], timeout)


@fail_on
def blockdev_snapshot(vm, source, target, **extra_options):
    cmd, arguments = blockdev_snapshot_qmp_cmd(source, target, **extra_options)
    out = vm.monitor.cmd(cmd, arguments)
    assert out == {}, "blockdev-snapshot-sync faild: %s" % out


@fail_on
def blockdev_mirror_nowait(vm, source, target, **extra_options):
    """Don't wait mirror completed, return job id"""
    cmd, arguments = blockdev_mirror_qmp_cmd(source, target, **extra_options)
    vm.monitor.cmd(cmd, arguments)
    return arguments.get("job-id", source)


@fail_on
def blockdev_mirror(vm, source, target, **extra_options):
    timeout = int(extra_options.pop("timeout", 600))
    job_id = blockdev_mirror_nowait(vm, source, target, **extra_options)
    job_utils.wait_until_block_job_completed(vm, job_id, timeout)


@fail_on
def block_commit(vm, device, **extra_options):
    cmd, arguments = block_commit_qmp_cmd(device, **extra_options)
    set_default_block_job_options(vm, arguments)
    timeout = int(extra_options.pop("timeout", 600))
    vm.monitor.cmd(cmd, arguments)
    job_id = arguments.get("job-id", device)
    job_utils.wait_until_block_job_completed(vm, job_id, timeout)


@fail_on
def blockdev_stream_nowait(vm, device, **extra_options):
    """Do block-stream and don't wait stream completed, return job id"""
    cmd, arguments = blockdev_stream_qmp_cmd(device, **extra_options)
    set_default_block_job_options(vm, arguments)
    vm.monitor.cmd(cmd, arguments)
    return arguments.get("job-id", device)


@fail_on
def blockdev_stream(vm, device, **extra_options):
    """Do block-stream and wait stream completed"""
    timeout = int(extra_options.pop("timeout", 600))
    job_id = blockdev_stream_nowait(vm, device, **extra_options)
    job_utils.wait_until_block_job_completed(vm, job_id, timeout)


@fail_on
def blockdev_backup(vm, source, target, **extra_options):
    cmd, arguments = blockdev_backup_qmp_cmd(source, target, **extra_options)
    timeout = int(extra_options.pop("timeout", 600))
    if "bitmap" in arguments:
        info = block_bitmap.get_bitmap_by_name(vm, source, arguments["bitmap"])
        assert info, "Bitmap '%s' not exists in device '%s'" % (
            arguments["bitmap"],
            source,
        )
        auto_disable_bitmap = extra_options.pop("auto_disable_bitmap", True)
        if auto_disable_bitmap and info.get("status") != "disabled":
            block_bitmap.block_dirty_bitmap_disable(vm, source, arguments["bitmap"])
    vm.monitor.cmd(cmd, arguments)
    job_id = arguments.get("job-id", source)
    job_utils.wait_until_block_job_completed(vm, job_id, timeout)


@fail_on
def blockdev_batch_snapshot(vm, source_lst, target_lst, **extra_options):
    actions = []
    timeout = int(extra_options.pop("timeout", 600))
    jobs_id = []
    for idx, src in enumerate(source_lst):
        snapshot_cmd, arguments = blockdev_snapshot_qmp_cmd(
            src, target_lst[idx], **extra_options
        )
        actions.append({"type": snapshot_cmd, "data": arguments})
    arguments = {"actions": actions}
    vm.monitor.cmd("transaction", arguments)
    list(
        map(lambda x: job_utils.wait_until_block_job_completed(vm, x, timeout), jobs_id)
    )


@fail_on
def blockdev_batch_backup(vm, source_lst, target_lst, bitmap_lst, **extra_options):
    actions = []
    jobs_id = []
    bitmap_add_cmd = "block-dirty-bitmap-add"
    timeout = int(extra_options.pop("timeout", 600))
    completion_mode = extra_options.pop("completion_mode", None)
    sync_mode = extra_options.get("sync")

    # we can disable dirty-map in a transaction
    bitmap_disable_cmd = "block-dirty-bitmap-disable"
    disabled_bitmap_lst = extra_options.pop("disabled_bitmaps", None)

    # sometimes the job will never complete, e.g. backup in pull mode,
    # export fleecing image by internal nbd server
    wait_job_complete = extra_options.pop("wait_job_complete", True)

    for idx, src in enumerate(source_lst):
        if sync_mode in ["incremental", "bitmap"]:
            assert len(bitmap_lst) == len(
                source_lst
            ), "must provide a valid bitmap name for 'incremental' sync mode"
            extra_options["bitmap"] = bitmap_lst[idx]
        backup_cmd, arguments = blockdev_backup_qmp_cmd(
            src, target_lst[idx], **extra_options
        )
        job_id = arguments.get("job-id", src)
        jobs_id.append(job_id)
        actions.append({"type": backup_cmd, "data": arguments})

        if bitmap_lst and (sync_mode == "full" or sync_mode == "none"):
            bitmap_data = {"node": source_lst[idx], "name": bitmap_lst[idx]}
            granularity = extra_options.get("granularity")
            persistent = extra_options.get("persistent")
            disabled = extra_options.get("disabled")
            if granularity is not None:
                bitmap_data["granularity"] = int(granularity)
            if persistent is not None:
                bitmap_data["persistent"] = persistent
            if disabled is not None:
                bitmap_data["disabled"] = disabled
            actions.append({"type": bitmap_add_cmd, "data": bitmap_data})

        if disabled_bitmap_lst:
            bitmap_data = {"node": source_lst[idx], "name": disabled_bitmap_lst[idx]}
            actions.append({"type": bitmap_disable_cmd, "data": bitmap_data})

    arguments = {"actions": actions}
    if completion_mode == "grouped":
        arguments["properties"] = {"completion-mode": "grouped"}
    vm.monitor.cmd("transaction", arguments)

    if wait_job_complete:
        list(
            map(
                lambda x: job_utils.wait_until_block_job_completed(vm, x, timeout),
                jobs_id,
            )
        )


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
    """Do full backup for node"""
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


def create_image_with_data_file(vm, params, image_name):
    """
    Create image with data_file
    :param vm: vm object
    :param params: params used to create data_file
    :image_name: image that created on data_file_image
    :return list: data_file image list
    """
    image_list = []
    image_params = params.object_params(image_name)
    data_file_tag = image_params.get("image_data_file")
    if data_file_tag:
        data_file_image = sp_admin.volume_define_by_params(data_file_tag, params)
        data_file_image.hotplug(vm)
        image_list.append(data_file_image)
    image = sp_admin.volume_define_by_params(image_name, params)
    image.hotplug(vm)
    image_list.append(image)
    return image_list


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
            partition="mbr",
        )
    finally:
        process.system("setenforce %s" % selinux_mode, shell=True)


def copyif(params, nbd_image, target_image, bitmap=None):
    """
    Python implementation of copyif3.sh
    :params params: utils_params.Params object
    :params nbd_image: nbd image tag
    :params target_image: target image tag
    :params bitmap: bitmap name
    """

    def _qemu_io_read(qemu_io, s, l, img):
        cmd = '{io} -C -c "r {s} {l}" -f {fmt} {f}'.format(
            io=qemu_io, s=s, l=l, fmt=img.image_format, f=img.image_filename
        )
        process.system(cmd, ignore_status=False, shell=True)

    qemu_io = utils_misc.get_qemu_io_binary(params)
    qemu_img = utils_misc.get_qemu_img_binary(params)
    img_obj = qemu_storage.QemuImg(
        params.object_params(target_image), data_dir.get_data_dir(), target_image
    )
    nbd_img_obj = qemu_storage.QemuImg(params.object_params(nbd_image), None, nbd_image)
    max_len = int(params.get("qemu_io_max_len", 2147483136))

    if bitmap is None:
        args = "-f %s %s" % (nbd_img_obj.image_format, nbd_img_obj.image_filename)
        state = True
    else:
        opts = qemu_storage.filename_to_file_opts(nbd_img_obj.image_filename)
        opt = params.get("dirty_bitmap_opt", "x-dirty-bitmap")
        opts[opt] = "qemu:dirty-bitmap:%s" % bitmap
        args = "'json:%s'" % json.dumps(opts)
        state = False

    img_obj.base_image_filename = nbd_img_obj.image_filename
    img_obj.base_format = nbd_img_obj.image_format
    img_obj.base_tag = nbd_img_obj.tag
    img_obj.rebase(img_obj.params)

    map_cmd = "{qemu_img} map --output=json {args}".format(qemu_img=qemu_img, args=args)
    result = process.run(map_cmd, ignore_status=False, shell=True)

    for item in json.loads(result.stdout.decode().strip()):
        if item["data"] is not state:
            continue

        # qemu-io can only handle length less than 2147483136,
        # so here we need to split 'large length' into several parts
        start, length = item["start"], item["length"]
        while length > max_len:
            _qemu_io_read(qemu_io, start, max_len, img_obj)
            start, length = start + max_len, length - max_len
        else:
            if length > 0:
                _qemu_io_read(qemu_io, start, length, img_obj)

    img_obj.base_tag = "null"
    img_obj.rebase(img_obj.params)


def get_disk_info_by_param(tag, params, session):
    """
    Get disk info by by serial/wwn or by size.

    For most cases, only one data disk is used, we can use disk size to find
    it; if there are more than one, we should set the same wwn/serial for each
    data disk and its target, e.g.
      blk_extra_params_data1 = "serial=DATA_DISK1"
      blk_extra_params_mirror1 = "serial=DATA_DISK1"
      blk_extra_params_data2 = "serial=DATA_DISK2"
      blk_extra_params_mirror2 = "serial=DATA_DISK2"
    where mirror1/mirror2 are the mirror images of data1/data2, so when we
    restart vm with mirror1 and mirror2, we can find them by serials
    :param tag: image tag name
    :param params: Params object
    :param session: vm login session
    :return: The disk info dict(e.g. {'kname':xx, 'size':xx}) or None
    """
    info = None
    drive_path = None
    image_params = params.object_params(tag)
    if image_params.get("blk_extra_params"):
        # get disk by serial or wwn
        # utils_disk.get_linux_disks can also get serial, but for
        # virtio-scsi ID_SERIAL is a long string including serial
        # e.g. ID_SERIAL=0QEMU_QEMU_HARDDISK_DATA_DISK2 instead of
        # ID_SERIAL=DATA_DISK2
        m = re.search(r"(serial|wwn)=(\w+)", image_params["blk_extra_params"], re.M)
        if m is not None:
            drive_path = utils_misc.get_linux_drive_path(session, m.group(2))

    if drive_path:
        info = {"kname": drive_path[5:], "size": image_params["image_size"]}
    else:
        # get disk by disk size
        conds = {
            "type": image_params.get("disk_type", "disk"),
            "size": image_params["image_size"],
        }
        disks = utils_disk.get_linux_disks(session, True)
        for kname, attr in disks.items():
            d = dict(zip(["kname", "size", "type"], attr))
            if all([conds[k] == d[k] for k in conds]):
                info = d
                break
    return info


@fail_on
def refresh_mounts(mounts, params, session):
    """
    Refresh mounts with the correct device and its mount point.

    Device name may change when restarting vm with the target images on RHEL9
    (e.g. start vm with mirror/snapshot/backup image as its data images)
    :param mounts: {tag, [dev path(e.g. /dev/sdb1), mnt(e.g. /mnt/sdb1)], ...}
    :param params: Params object
    :param session: vm login session
    """
    # always refresh disks info when count of data disks >= 1
    for tag, mount in mounts.items():
        if tag == "image1":
            continue
        info = get_disk_info_by_param(tag, params, session)
        assert info, "Failed to get the kname for device: %s" % tag
        mount[0] = "/dev/%s1" % info["kname"]
