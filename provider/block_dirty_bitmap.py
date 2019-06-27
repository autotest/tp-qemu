"""
Module to provide functions related to block dirty bitmap operations.
"""
import time
import logging
from functools import partial

from avocado import fail_on

from virttest import data_dir
from virttest import storage
from virttest import utils_misc


def parse_params(vm, params):
    """Parse params for bitmap."""
    bitmaps = []
    for bitmap in params.get("bitmaps", "").split():
        bitmap_params = params.object_params(bitmap)
        bitmap_params.setdefault("bitmap_name", bitmap)
        target_image = bitmap_params.get("target_image")
        target_image_params = params.object_params(target_image)
        target_image_filename = storage.get_image_filename(
            target_image_params, data_dir.get_data_dir())
        target_device = vm.get_block({"file": target_image_filename})
        bitmap_params["target_device"] = target_device
        bitmaps.append(bitmap_params)
    return bitmaps


def get_bitmaps(output):
    """Get bitmaps for each device from query-block output.

    :param output: query-block output
    """
    return {d["device"]: d.get("dirty-bitmaps", []) for d in output}


def check_bitmap_existence(bitmaps, bitmap_params, expected_existence=True):
    """Check bitmap existence is same as expected.

    :param bitmaps: bitmaps info dict
    :param bitmap_params: bitmap params
    :param expected_existence: True to check for existence
    """
    bname = bitmap_params.get("bitmap_name")
    dev = bitmap_params.get("target_device")
    bitmap = (dev in bitmaps and
              next((b for b in bitmaps[dev] if b["name"] == bname), {}))
    return bool(bitmap) == expected_existence


@fail_on
def block_dirty_bitmap_add(vm, bitmap_params):
    """Add block dirty bitmap."""
    bitmap = bitmap_params.get("bitmap_name")
    target_device = bitmap_params.get("target_device")
    persistent = bitmap_params.get("persistent", "default")
    logging.debug("add dirty bitmap %s to %s", bitmap, target_device)
    kargs = dict(node=target_device, name=bitmap)
    _ = "persistent"
    kargs.update(
        {"on": {_: True}, "off": {_: False}, "default": {_: None}}[persistent]
    )
    vm.monitor.block_dirty_bitmap_add(**kargs)


@fail_on
def debug_block_dirty_bitmap_sha256(vm, device, bitmap):
    """
    Get sha256 vaule of bitmap in the device

    :param device: device name
    :param bitmap: bitmap name
    :return: sha256 string or None if bitmap is not exists
    """
    func = utils_misc.get_monitor_function(vm)
    return func(device, bitmap).get("sha256")


def block_dirty_bitmap_merge(vm, device, bitmaps, target):
    """
    Merge dirty bitmaps in the device to target

    :param vm: VM object
    :param device: device id or node name
    :param bitmaps: source bitmaps
    :param target: target bitmap name
    """
    func = utils_misc.get_monitor_function(vm)
    cmd = func.__name__.replace("_", "-")
    logging.debug("Merge %s into %s" % (bitmaps, target))
    if not cmd.startswith("x-"):
        return func(device, bitmaps, target)
    # handle 'x-block-dirty-bitmap-merge' command
    if len(bitmaps) == 1:
        return func(device, bitmaps[0], target)
    actions = []
    for bitmap in bitmaps:
        data = {"node": device, "src_bitmap": bitmap, "dst_bitmap": target}
        actions.append({"type": cmd, "data": data})
    return vm.monitor.transalation(actions)


def get_bitmap_by_name(vm, device, name):
    """
    Get device bitmap info by bitmap name

    :param device: device name
    :param bitmap: bitmap name
    :return: bitmap info dict or None if bitmap is not exists
    """
    info = get_bitmaps_in_device(vm, device)
    bitmaps = [_ for _ in info if _.get("name") == name]
    if bitmaps:
        return bitmaps[0]
    return None


@fail_on
def block_dirty_bitmap_clear(vm, device, name):
    utils_misc.get_monitor_function(vm)(device, name)
    time.sleep(0.3)
    msg = "Count of '%s' in device '%s' not equal '0' after clear it" % (
        device, name)
    count = get_bitmap_by_name(vm, device, name)["count"]
    assert int(count) == 0, msg


@fail_on
def clear_all_bitmaps_in_device(vm, device):
    """Clear bitmaps on the device one by one"""
    bitmaps = get_bitmaps_in_device(vm, device)
    names = [_["name"] for _ in bitmaps if _.get("name")]
    func = partial(block_dirty_bitmap_clear, vm, device)
    map(func, names)


@fail_on
def block_dirty_bitmap_remove(vm, device, name):
    """Remove bitmaps on the device one by one"""
    utils_misc.get_monitor_function(vm)(device, name)
    time.sleep(0.3)
    msg = "Bitmap '%s' in device '%s' still exists!" % (name, device)
    assert get_bitmap_by_name(vm, device, name) is None, msg


@fail_on
def remove_all_bitmaps_in_device(vm, device):
    """Remove bitmaps on the device one by one"""
    bitmaps = get_bitmaps_in_device(vm, device)
    names = [_["name"] for _ in bitmaps if _.get("name")]
    func = partial(block_dirty_bitmap_remove, vm, device)
    map(func, names)


@fail_on
def block_dirty_bitmap_disable(vm, node, name):
    """Disable named block dirty bitmap in the node"""
    func = utils_misc.get_monitor_function(vm)(node, name)
    bitmap = get_bitmap_by_name(vm, node, name)
    msg = "block dirty bitmap '%s' is not disabled" % name
    assert bitmap["status"] == "disabled", msg


def get_bitmaps_in_device(vm, device):
    """Get bitmap info list in given device"""
    out = vm.monitor.cmd("query-block")
    bitmaps = get_bitmaps(out)
    return bitmaps.get(device, list())
