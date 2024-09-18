import json
import socket

from avocado.utils import process
from virttest import data_dir, utils_misc, utils_qemu
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg
from virttest.utils_version import VersionInterval

from provider.nbd_image_export import QemuNBDExportImage


def run(test, params, env):
    """
    Creating a qcow2 image and test bitmap suboptions over the image.
    1. Test --add sub command.
    2. Test --remove sub command.
    3. Test --disable sub command.
    4. Test --enable sub command.
    5. Test --clear sub command.
    6. Test --merge sub command.

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError as err:
            test.fail("qemu-io to '%s' failed: %s." % (img.image_filename, str(err)))

    def _map_nbd_bitmap(nbd_server, nbd_port, bitmap_name):
        """ "qemu-img map an image over NBD with bitmap"""
        map_from = "--image-opts driver=nbd,server.type=inet,server.host=%s"
        map_from += ",server.port=%s,x-dirty-bitmap=qemu:dirty-bitmap:%s"
        map_from %= (nbd_server, nbd_port, bitmap_name)
        qemu_map_cmd = "qemu-img map --output=json %s" % map_from
        result = process.run(qemu_map_cmd, shell=True).stdout_text
        json_data = json.loads(result)
        return json_data

    def _check_bitmap_add(img, bitmap_name):
        """ "Check the result of bitmap add"""
        add_bitmap_info = [
            {"flags": ["auto"], "name": "%s" % bitmap_name, "granularity": 65536}
        ]
        info_output = json.loads(img.info(output="json"))
        if "bitmaps" not in info_output["format-specific"]["data"]:
            test.fail("Add bitmap failed, and image info is '%s'" % info_output)
        elif add_bitmap_info != info_output["format-specific"]["data"]["bitmaps"]:
            test.fail(
                "The bitmap info is not correct, and the complete image info "
                "is '%s'" % info_output
            )

    images = params["images"].split()
    bitmap = images[0]
    root_dir = data_dir.get_data_dir()
    bitmap_img = QemuImg(params.object_params(bitmap), root_dir, bitmap)
    bitmap_name = params["bitmap_name"]

    qemu_binary = utils_misc.get_qemu_binary(params)
    qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]

    # --add command
    test.log.info("Add bitmap to the test image.")
    bitmap_img.bitmap_add(bitmap_name)
    _check_bitmap_add(bitmap_img, bitmap_name)

    # --disable command
    test.log.info("Disable bitmap of the test image.")
    bitmap_img.bitmap_disable(bitmap_name)
    info_output = json.loads(bitmap_img.info(output="json"))
    if info_output["format-specific"]["data"]["bitmaps"][0]["flags"]:
        test.fail("Disable bitmap failed, and image info is '%s'" % info_output)

    # --enable command
    test.log.info("Enable bitmap of the test image.")
    bitmap_img.bitmap_enable(bitmap_name)
    info_output = json.loads(bitmap_img.info(output="json"))
    if "auto" not in info_output["format-specific"]["data"]["bitmaps"][0]["flags"]:
        test.fail("Enable bitmap failed, and image info is '%s'" % info_output)

    # --clear command
    test.log.info("Clear bitmap of the test image.")
    _qemu_io(bitmap_img, "write -P1 0 1M")
    # export the image over NBD
    nbd_export = QemuNBDExportImage(params, bitmap)
    nbd_export.export_image()
    nbd_image_tag = params["nbd_image_tag"]
    nbd_image_params = params.object_params(nbd_image_tag)
    localhost = socket.gethostname()
    nbd_image_params["nbd_server"] = localhost if localhost else "localhost"

    # Map the image over NBD with bitmap
    nbd_server = nbd_image_params["nbd_server"]
    nbd_port = params["nbd_port_bitmap_test"]
    nbd_export_bitmap = params["bitmap_name"]
    try:
        res = _map_nbd_bitmap(nbd_server, nbd_port, nbd_export_bitmap)
        match_info = {
            "start": 0,
            "length": 1048576,
            "depth": 0,
            "present": False,
            "zero": False,
            "data": False,
        }
        if qemu_version in VersionInterval("[8.2.0,)"):
            match_info["compressed"] = False
        if match_info not in res:
            test.fail("The dumped info is not correct, and the info is %s" % res)
    finally:
        nbd_export.stop_export()
    # Execute bitmap clear
    bitmap_img.bitmap_clear(bitmap_name)
    # Export again to check whether the bitmap data cleared
    nbd_export.export_image()
    try:
        res = _map_nbd_bitmap(nbd_server, nbd_port, nbd_export_bitmap)
        if match_info in res:
            test.fail("Clear the bitmap data failed, and the dumped info is %s" % res)
    finally:
        nbd_export.stop_export()

    # --merge command
    bitmap_name_top = params["bitmap_name_top"]
    top = images[1]
    root_dir = data_dir.get_data_dir()
    top_img = QemuImg(params.object_params(top), root_dir, top)

    # add bitmap to top image
    test.log.info("Add bitmap to the top image.")
    top_img.bitmap_add(bitmap_name_top)
    _check_bitmap_add(top_img, params["bitmap_name_top"])
    # write data to test and top images
    _qemu_io(bitmap_img, "write -P1 0 1M")
    _qemu_io(top_img, "write -P2 1M 1M")
    # check the info before merging
    nbd_export.export_image()
    try:
        res = _map_nbd_bitmap(nbd_server, nbd_port, nbd_export_bitmap)
        match_info = {
            "start": 0,
            "length": 1048576,
            "depth": 0,
            "present": False,
            "zero": False,
            "data": False,
        }
        if qemu_version in VersionInterval("[8.2.0,)"):
            match_info["compressed"] = False
        if match_info not in res:
            test.fail(
                "Add the bitmap data to base image failed, and the dumped "
                "info is %s" % res
            )
    finally:
        nbd_export.stop_export()
    # merge the bitmap of top image to base image
    bitmap_source = params["bitmap_source"]
    bitmap_img.bitmap_merge(
        params, root_dir, bitmap_name_top, bitmap_name, bitmap_source
    )
    # Check the info of base after merging
    nbd_export.export_image()
    try:
        res = _map_nbd_bitmap(nbd_server, nbd_port, nbd_export_bitmap)
        match_info = {
            "start": 0,
            "length": 2097152,
            "depth": 0,
            "present": False,
            "zero": False,
            "data": False,
        }
        if qemu_version in VersionInterval("[8.2.0,)"):
            match_info["compressed"] = False
        if match_info not in res:
            test.fail(
                "Add the bitmap data to base image failed, and the dumped "
                "info is %s" % res
            )
    finally:
        nbd_export.stop_export()

    # --remove command
    test.log.info("Remove bitmap of the test image.")
    bitmap_img.bitmap_remove(bitmap_name)
    info_output = json.loads(bitmap_img.info(output="json"))
    if "bitmaps" in info_output["format-specific"]["data"]:
        test.fail("Remove bitmap failed, and image info is '%s'" % info_output)
