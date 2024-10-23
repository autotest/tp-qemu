"""
Module to provide functions related to block dirty bitmap operations.
"""

import logging
import time
from functools import partial

from avocado import fail_on
from virttest import data_dir, qemu_monitor, qemu_storage, storage

LOG_JOB = logging.getLogger("avocado.test")


def parse_params(vm, params):
    """Parse params for bitmap."""
    bitmaps = []
    for bitmap in params.get("bitmaps", "").split():
        bitmap_params = params.object_params(bitmap)
        bitmap_params.setdefault("bitmap_name", bitmap)
        target_image = bitmap_params.get("target_image")
        target_image_params = params.object_params(target_image)
        json_backend_list = ["ceph", "iscsi_direct"]
        if target_image_params["image_backend"] in json_backend_list:
            get_image_name = qemu_storage.get_image_json
            target_image_filename = get_image_name(
                target_image, target_image_params, data_dir.get_data_dir()
            )
        else:
            target_image_filename = storage.get_image_filename(
                target_image_params, data_dir.get_data_dir()
            )
        target_device = vm.get_block({"file": target_image_filename})
        bitmap_params["target_device"] = target_device
        bitmaps.append(bitmap_params)
    return bitmaps


def get_bitmaps(output):
    """Get bitmaps for each device from query-block output.

    :param output: query-block output
    """
    bitmaps_dict, default = {}, []
    for item in output:
        # Notes:
        #    if dirty-bitmaps in output, output is BlockInfo
        #    format, else output is BlockDeviceInfo format
        if "dirty-bitmaps" in item:
            bitmaps = item.get("dirty-bitmaps", default)
        else:
            bitmaps = item["inserted"].get("dirty-bitmaps", default)
        key = item["device"] or item["inserted"]["node-name"]
        bitmaps_dict[key] = bitmaps
    return bitmaps_dict


def check_bitmap_existence(bitmaps, bitmap_params, expected_existence=True):
    """Check bitmap existence is same as expected.

    :param bitmaps: bitmaps info dict
    :param bitmap_params: bitmap params
    :param expected_existence: True to check for existence
    """
    bname = bitmap_params.get("bitmap_name")
    dev = bitmap_params.get("target_device")
    bitmap = dev in bitmaps and next(
        (b for b in bitmaps[dev] if b["name"] == bname), {}
    )
    return bool(bitmap) == expected_existence


@fail_on
def block_dirty_bitmap_add(vm, bitmap_params):
    """Add block dirty bitmap."""
    bitmap = bitmap_params.get("bitmap_name")
    target_device = bitmap_params.get("target_device")
    LOG_JOB.debug("add dirty bitmap %s to %s", bitmap, target_device)
    mapping = {}
    for item in ["persistent", "disabled"]:
        mapping[item] = {
            "on": {item: True},
            "off": {item: False},
            "default": {item: None},
        }
    kargs = dict(node=target_device, name=bitmap)
    if bitmap_params.get("bitmap_granularity"):
        kargs["granularity"] = bitmap_params["bitmap_granularity"]
    for item in ["persistent", "disabled"]:
        kargs.update(mapping[item][bitmap_params.get(item, "default")])
    vm.monitor.block_dirty_bitmap_add(**kargs)


@fail_on
def debug_block_dirty_bitmap_sha256(vm, device, bitmap):
    """
    Get sha256 vaule of bitmap in the device

    :param device: device name
    :param bitmap: bitmap name
    :return: sha256 string or None if bitmap is not exists
    """
    func = qemu_monitor.get_monitor_function(vm, "debug-block-dirty-bitmap-sha256")
    return func(device, bitmap).get("sha256")


def block_dirty_bitmap_merge(vm, device, bitmaps, target):
    """
    Merge dirty bitmaps in the device to target

    :param vm: VM object
    :param device: device id or node name
    :param bitmaps: source bitmaps
    :param target: target bitmap name
    """
    func = qemu_monitor.get_monitor_function(vm, "block-dirty-bitmap-merge")
    cmd = func.__name__.replace("_", "-")
    LOG_JOB.debug("Merge %s into %s", bitmaps, target)
    if not cmd.startswith("x-"):
        return func(device, bitmaps, target)
    # handle 'x-block-dirty-bitmap-merge' command
    if len(bitmaps) == 1:
        return func(device, bitmaps[0], target)
    actions = []
    for bitmap in bitmaps:
        data = {"node": device, "src_name": bitmap, "dst_name": target}
        actions.append({"type": cmd, "data": data})
    return vm.monitor.transaction(actions)


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
    qemu_monitor.get_monitor_function(vm, "block-dirty-bitmap-clear")(device, name)
    count = int(get_bitmap_by_name(vm, device, name)["count"])
    msg = "Count of '%s' in device '%s'" % (name, device)
    msg += "is '%d' not equal '0' after clear it" % count
    assert count == 0, msg


@fail_on
def clear_all_bitmaps_in_device(vm, device):
    """Clear bitmaps on the device one by one"""
    bitmaps = get_bitmaps_in_device(vm, device)
    names = [_["name"] for _ in bitmaps if _.get("name")]
    func = partial(block_dirty_bitmap_clear, vm, device)
    list(map(func, names))


@fail_on
def block_dirty_bitmap_remove(vm, device, name):
    """Remove bitmaps on the device one by one"""
    qemu_monitor.get_monitor_function(vm, "block-dirty-bitmap-remove")(device, name)
    time.sleep(0.3)
    msg = "Bitmap '%s' in device '%s' still exists!" % (name, device)
    assert get_bitmap_by_name(vm, device, name) is None, msg


@fail_on
def remove_all_bitmaps_in_device(vm, device):
    """Remove bitmaps on the device one by one"""
    bitmaps = get_bitmaps_in_device(vm, device)
    names = [_["name"] for _ in bitmaps if _.get("name")]
    func = partial(block_dirty_bitmap_remove, vm, device)
    list(map(func, names))


@fail_on
def block_dirty_bitmap_disable(vm, node, name):
    """Disable named block dirty bitmap in the node"""
    func = qemu_monitor.get_monitor_function(vm, "block-dirty-bitmap-disable")
    func(node, name)
    bitmap = get_bitmap_by_name(vm, node, name)
    msg = "block dirty bitmap '%s' is not disabled" % name
    assert bitmap["recording"] is False, msg


@fail_on
def block_dirty_bitmap_enable(vm, node, name):
    """Enable named block dirty bitmap in the node"""
    func = qemu_monitor.get_monitor_function(vm, "block-dirty-bitmap-enable")
    func(node, name)
    bitmap = get_bitmap_by_name(vm, node, name)
    msg = "block dirty bitmap '%s' is not enabled" % name
    assert bitmap["recording"] is True, msg


def get_bitmaps_in_device(vm, device):
    """Get bitmap info list in given device"""
    out = vm.monitor.cmd("query-block")
    bitmaps = get_bitmaps(out)
    return bitmaps.get(device, list())


@fail_on
def handle_block_dirty_bitmap_transaction(
    vm, disabled_params=None, added_params=None, merged_params=None
):
    """
    Add/disable/merge bitmaps in one transaction.
    :param vm: an active VM object
    :param disabled_params: dict for bitmaps to be disabled,
                  required: bitmap_device_node, bitmap_name
                  optional: bitmap_disable_cmd
    :param added_params: dict for bitmaps to be added,
               required: bitmap_device_node, bitmap_name
               optional: bitmap_add_cmd, bitmap_granularity,
                         bitmap_persistent, bitmap_disabled
    :param merged_params: dict for bitmaps to be merged
                required: bitmap_device_node, bitmap_target, bitmap_sources
                optional: bitmap_merge_cmd
    """
    actions = []

    if disabled_params:
        bitmap_disable_cmd = disabled_params.get(
            "bitmap_disable_cmd", "block-dirty-bitmap-disable"
        )
        bitmap_data = {
            "node": disabled_params["bitmap_device_node"],
            "name": disabled_params["bitmap_name"],
        }
        actions.append({"type": bitmap_disable_cmd, "data": bitmap_data})

    if added_params:
        bitmap_add_cmd = added_params.get("bitmap_add_cmd", "block-dirty-bitmap-add")
        bitmap_data = {
            "node": added_params["bitmap_device_node"],
            "name": added_params["bitmap_name"],
        }
        if added_params.get("bitmap_granularity"):
            bitmap_data["granularity"] = added_params["bitmap_granularity"]

        mapping = {"on": True, "yes": True, "off": False, "no": False}
        if added_params.get("bitmap_persistent"):
            bitmap_data["persistent"] = mapping[added_params["bitmap_persistent"]]
        if added_params.get("bitmap_disabled"):
            bitmap_data["disabled"] = mapping[added_params["bitmap_disabled"]]
        actions.append({"type": bitmap_add_cmd, "data": bitmap_data})

    if merged_params:
        bitmap_merge_cmd = merged_params.get(
            "bitmap_merge_cmd", "block-dirty-bitmap-merge"
        )
        bitmap_data = {
            "node": merged_params["bitmap_device_node"],
            "target": merged_params["bitmap_target"],
            "bitmaps": merged_params["bitmap_sources"],
        }
        actions.append({"type": bitmap_merge_cmd, "data": bitmap_data})

    if actions:
        arguments = {"actions": actions}
        vm.monitor.cmd("transaction", arguments)
