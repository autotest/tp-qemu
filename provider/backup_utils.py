import sys
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
default_recursionlimit = sys.getrecursionlimit()
sys.setrecursionlimit(default_recursionlimit * 5)

def merge_options(options1, options2):
    """Merge dict options2 into dict options1"""
    if not isinstance(options2, dict):
        return options1 
    options2 = dict([(k,v) for k,v in options2.items() if v is not None])
    options1.update(options2)
    return options1

@utils_scheduling.timeout(MAX_JOB_TIMEOUT)
def blockdev_create(vm, options, job_id=None, wait_for=True):
    """wrapper for blockdev-create QMP command"""
    def wait(job_id):
        job_info = job_utils.get_job_by_id(vm, job_id)
        status = job_info.get("status")
        if status == "concluded":
            return True
        time.sleep(1.0)
        return wait(job_id)

    if not job_id:
        job_id = "blk_%s" % utils_misc.generate_random_id()
    func = qemu_monitor.get_monitor_function(vm, "blockdev-create")
    func(job_id, options)
    wait(job_id)
    return job_id


@utils_scheduling.timeout(MAX_JOB_TIMEOUT)
def blockdev_backup(vm, options, wait_for):
    """
    Live backup block device

    :param vm: VM object
    :param options: dict for blockdev-backup cmd
    :param wait: bool type, wait for backup job finished or not
    """
    def wait(job_id):
        job_info = job_utils.get_job_by_id(vm, job_id)
        args = {"id": job_id}
        status = job_info.get("status", None)
        if status == "pending" and options.get("auto-finalize") == False:
             vm.monitor.cmd("block-job-finalize", args) 
        elif status == "concluded" and options.get("auto-dismiss") == False:
             vm.monitor.cmd("block-job-dismiss", args)
        event = vm.monitor.get_event("BLOCK_JOB_COMPLETED")
        if event:
            return event["data"].get("error") 
        else:
            time.sleep(3)
        return wait(job_id)

    job_id = utils_misc.generate_random_id()
    options.setdefault("job-id", job_id)
    qemu_monitor.get_monitor_function(vm, "blockdev-backup")(options)
    vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
    error = wait(job_id)
    assert error is None, "Block job failed with error '%s'" % error
    node_info = get_block_node_by_name(vm, options["target"])
    return node_info["image"]["filename"]

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
    return info[0] if info else dict() 


def query_named_block_nodes(vm):
    """Get all block nodes info of the VM"""
    func = qemu_monitor.get_monitor_function(vm, "query-named-block-nodes")
    return func()


@fail_on
def incremental_backup(vm, node, target, bitmap=None, options=None, wait=True):
    """
    Do incremental backup with bitmap

    :param vm: VM object
    :param node: device ID or node-name
    :param target: target device node-name or ID
    :param wait: wait for backup job finished or not
    """
    args = {
        "device": node,
        "target": target,
        "sync": "incremental"}
    if bitmap:
        args["bitmap"] = bitmap
        info = block_bitmap.get_bitmap_by_name(vm, node, bitmap)
        assert info, "Bitmap '%s' not exists in device '%s'" % (bitmap, node)
        if info["status"] != "disabled":
            block_bitmap.block_dirty_bitmap_disable(vm, node, bitmap)
    args = merge_options(args, options)
    return blockdev_backup(vm, args, wait)


@fail_on
def full_backup(vm, node, target, options=None, wait=True):
    """ Do full backup for node"""
    args = {
        "device": node,
        "target": target,
        "sync": "full"}
    args = merge_options(args, options)
    return blockdev_backup(vm, args, wait)


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
        "file": img_node_name,
        }
    if params.get("cluster_size"):
        format_image_options.update(
            {"cluster-size": int(params["cluster_size"])})
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
