import socket

from avocado.utils import process
from virttest import data_dir, qemu_storage
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg

from provider.nbd_image_export import QemuNBDExportImage


def run(test, params, env):
    """
    Check the dump info of snapshot files over nbd.
    1. Create a base image with 4 clusters of 64k.
    3. Create a top snapshot based on the base image.
    4. Write data to the first/second/third cluster of the base image file.
    5. Write data to the second/third cluster of the top image.
    6. Export the snapshot image over NBD.
    7. Check the dump info of the snapshot over NBD.
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

    images = params["image_chain"].split()
    base_img = images[0]
    top_img = images[1]
    root_dir = data_dir.get_data_dir()
    base = QemuImg(params.object_params(base_img), root_dir, base_img)
    top = QemuImg(params.object_params(top_img), root_dir, top_img)

    # write data to the base image
    _qemu_io(base, params["base_io_cmd_01"])
    _qemu_io(base, params["base_io_cmd_02"])
    _qemu_io(base, params["base_io_cmd_03"])

    # write data to the top image
    _qemu_io(top, params["top_io_cmd_01"])
    _qemu_io(top, params["top_io_cmd_02"])

    # export the top image over nbd
    nbd_export = QemuNBDExportImage(params, top_img)
    nbd_export.export_image()

    nbd_image_tag = params["nbd_image_tag"]
    nbd_image_params = params.object_params(nbd_image_tag)
    localhost = socket.gethostname()
    nbd_image_params["nbd_server"] = localhost if localhost else "localhost"
    qemu_img = qemu_storage.QemuImg(nbd_image_params, None, nbd_image_tag)
    nbd_image = qemu_img.image_filename
    map_cmd = params["map_cmd"]
    check_msg = params["check_msg"]

    test.log.info("Dump the info of '%s'", nbd_image)
    try:
        result = process.run(map_cmd + " " + nbd_image, ignore_status=True, shell=True)
        if result.exit_status != 0:
            test.fail(
                "Failed to execute the map command, error message: %s"
                % result.stderr.decode()
            )
        elif check_msg not in result.stdout.decode().strip():
            test.fail(
                "Message '%s' mismatched with '%s'"
                % (check_msg, result.stdout.decode())
            )
    finally:
        nbd_export.stop_export()
