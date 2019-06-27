import time
from functools import partial

from avocado import fail_on

from virttest import utils_misc
from virttest import utils_numeric
from virttest import utils_scheduling
from virttest import storage
from virttest import data_dir
from virttest import qemu_monitor

from provider import job_utils
from provider import block_dirty_bitmap as block_bitmap

MAX_JOB_TIMEOUT = 1200


def blockdev_create(vm, options, job_id=None, wait=True):
    """wrapper for blockdev-create QMP command"""
    if not job_id:
        job_id = "blk_%s" % utils_misc.generate_random_id()
    qemu_monitor.get_monitor_function(vm, "blockdev-create")(job_id, options)
    if wait:
        def wait_func():
            job_info = job_utils.get_job_by_id(vm, job_id)
            if job_info and job_info["status"] == "concluded":
                return True
            return False

        if not utils_misc.wait_for(wait_func, 5, 1):
            return None
    return job_id


def blockdev_backup(vm, options, wait):
    """
    Live backup block device

    :param vm: VM object
    :param options: dict for blockdev-backup cmd
    :param wait: bool type, wait for backup job finished or not
    """
    event = "BLOCK_JOB_COMPLETED"
    job_id = utils_misc.generate_random_id()
    options.setdefault("job-id", job_id)
    out = qemu_monitor.get_monitor_function(vm, "blockdev-backup")(options)
    wait and wait_for_event(vm.monitor, event)
    return out


def blockdev_add(vm, options):
    """wrapper for blockdev-add QMP command"""
    if "node-name" not in options:
        options["node-name"] = utils_misc.generate_random_id()
    qemu_monitor.get_monitor_function(vm, "blockdev-add")(options)
    return options["node-name"]


def get_block_node_by_name(vm, node):
    """Get block node info by node name"""
    out = query_named_block_nodes(vm)
    info = [i for i in out if i["node-name"] == node]
    if info:
        return info[0]
    return None


def query_named_block_nodes(vm):
    """Get all block nodes info of the VM"""
    func = qemu_monitor.get_monitor_function(vm, "query-named-block-nodes")
    return func()


@fail_on
def incremental_backup(vm, node, target, bitmap=None, wait=True):
    """
    Do incremental backup with bitmap

    :param vm: VM object
    :param node: device ID or node-name
    :param target: target device node-name or ID
    :param wait: wait for backup job finished or not
    """
    options = {
        "device": node,
        "target": target,
        "sync": "incremental"}
    if bitmap:
        options["bitmap"] = bitmap
        info = block_bitmap.get_bitmap_by_name(vm, node, bitmap)
        assert info, "Bitmap '%s' not exists in device '%s'" % (bitmap, node)
        if info["status"] != "disabled":
            block_bitmap.block_dirty_bitmap_disable(vm, node, bitmap)
    return blockdev_backup(vm, options, wait)


@fail_on
def full_backup(vm, node, target, wait=True):
    """ Do full backup for node"""
    options = {
        "device": node,
        "target": target,
        "sync": "full"}
    return blockdev_backup(vm, options, wait)


@utils_scheduling.timeout(MAX_JOB_TIMEOUT)
def wait_for_event(monitor, event):
    """wait for get event in monitor timeout in seconds"""
    monitor.clear_event(event)
    while True:
        if monitor.get_event(event):
            break
        time.sleep(0.1)


@fail_on
def create_target_block_device(vm, params, backing_info):
    """Create target backup device by qemu"""
    jobs = list()
    image_dir = data_dir.get_data_dir()
    random_id = utils_misc.generate_random_id()
    img_node_name = "img_%s" % random_id
    dev_node_name = "dev_%s" % random_id
    image_size = align_image_size(params["image_size"])
    filename = storage.get_image_filename(params, image_dir)
    image_create_options = {
        "driver": params["image_type"],
        "filename": filename,
        "size": 0}
    image_add_options = {
        "driver": params["image_type"],
        "filename": filename,
        "node-name": img_node_name}
    format_image_options = {
        "driver": params["image_format"],
        "size": image_size,
        "file": img_node_name}
    add_device_options = {
        "driver": params["image_format"],
        "file": image_add_options["node-name"],
        "node-name": dev_node_name}
    if backing_info:
        format_image_options.update(
            {"backing-file": backing_info["backing-file"],
             "backing-fmt": backing_info["backing-fmt"]})
        add_device_options.update({"backing": backing_info["backing"]})
    try:
        jobs += [blockdev_create(vm, image_create_options)]
        blockdev_add(vm, image_add_options)
        jobs += [blockdev_create(vm, format_image_options)]
        blockdev_add(vm, add_device_options)
    finally:
        list(map(partial(job_utils.job_dismiss, vm), jobs))
    if get_block_node_by_name(vm, dev_node_name):
        return dev_node_name, filename
    return None, None


def align_image_size(image_size):
    """
    Get target image size align with 512

    :return: image size in Bytes
    """
    image_size = utils_numeric.normalize_data_size(
        image_size, 'B', 1024)
    return utils_numeric.align_value(image_size, 512)
