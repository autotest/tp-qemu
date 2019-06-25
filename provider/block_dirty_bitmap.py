"""
Module to provide functions related to block dirty bitmap operations.
"""
import logging

from avocado import fail_on

from virttest import data_dir
from virttest import storage


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
