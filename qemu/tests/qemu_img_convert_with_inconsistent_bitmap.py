import json

from avocado.utils import process
from virttest import data_dir, qemu_storage, utils_misc

from provider.nbd_image_export import QemuNBDExportImage


def run(test, params, env):
    """
    Convert image with parameter -B -n
    1. Create a data image
    2. Add a persistent bitmap to data image
    3. Check bitmap info of data image
    4. Expose data image with its bitmap
    5. Kill bitmap expose
    6. Check bitmap info of data image
    7. Add another persistent bitmap
    8. Check bitmap info of data image
    9. Convert data image with all bitmaps
       Make sure the values are the same
    10. Convert data image with inconsistent bitmap skipped
    11. Check bitmap info of convert target

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def add_persistent_bitmap_to_image(image, bitmap):
        """Add persistent bitmap to image"""
        qemu_img = utils_misc.get_qemu_img_binary(params)
        add_bitmap_cmd = "%s bitmap %s --add %s" % (qemu_img, image, bitmap)
        process.run(add_bitmap_cmd, ignore_status=False, shell=True)

    def export_image_with_bitmap(params, tag):
        """Expose image with bitmap"""
        global nbd_export
        nbd_export = QemuNBDExportImage(params, tag)
        nbd_export.export_image()

    def check_bitmap_in_image(image, bitmap_name, inconsistent=False):
        """Check bitmap info in image"""
        test.log.info("Verify bitmap info in image")
        info = json.loads(image.info(output="json"))
        bitmaps_info = info["format-specific"]["data"].get("bitmaps")
        for bitmap in bitmaps_info:
            if bitmap["name"] == bitmap_name:
                if inconsistent and "in-use" not in bitmap["flags"]:
                    test.fail("inconsistent bitmap not stored in image")
                break
        else:
            test.fail("Persistent bitmap not stored in image")

    def check_bitmap_not_in_image(image, bitmap_name):
        """Check bitmap info not in image"""
        test.log.info("Verify bitmap info not in image")
        info = json.loads(image.info(output="json"))
        bitmaps_info = info["format-specific"]["data"].get("bitmaps")
        for bitmap in bitmaps_info:
            if bitmap["name"] == bitmap_name:
                test.fail("Bitmap still in image")

    def convert_image_with_bitmaps(src_fmt, tar_fmt, src_name, tar_name):
        qemu_img = utils_misc.get_qemu_img_binary(params)
        convert_cmd = params["convert_cmd"] % (
            qemu_img,
            src_fmt,
            tar_fmt,
            src_name,
            tar_name,
        )
        try:
            process.system(convert_cmd, ignore_status=False, shell=True)
        except process.CmdError as e:
            if "Cannot copy inconsistent bitmap" in str(e):
                convert_cmd += " --skip-broken-bitmaps"
                process.system(convert_cmd, ignore_status=False, shell=True)
        else:
            test.fail("Can convert image with inconsistent bitmap included")

    def get_image_param_by_tag(root_dir, tag):
        parms = params.object_params(tag)
        image = qemu_storage.QemuImg(parms, root_dir, tag)
        name = image.image_filename
        return parms, name, image

    root_dir = data_dir.get_data_dir()
    src_tag = params["images"].split()[0]
    src_params, src_name, src_image = get_image_param_by_tag(root_dir, src_tag)
    dst_tag = params["convert_target"]
    dst_params, dst_name, dst_image = get_image_param_by_tag(root_dir, dst_tag)
    bitmaps = params["bitmaps"].split()
    add_persistent_bitmap_to_image(src_name, bitmaps[0])
    check_bitmap_in_image(src_image, bitmaps[0])
    export_image_with_bitmap(src_params, src_tag)
    nbd_export.stop_export()
    check_bitmap_in_image(src_image, bitmaps[0], inconsistent=True)
    add_persistent_bitmap_to_image(src_name, bitmaps[1])
    check_bitmap_in_image(src_image, bitmaps[1])
    try:
        convert_image_with_bitmaps(
            src_params["image_format"], dst_params["image_format"], src_name, dst_name
        )
        check_bitmap_not_in_image(dst_image, bitmaps[0])
        check_bitmap_in_image(dst_image, bitmaps[1])
    finally:
        dst_image.remove()
