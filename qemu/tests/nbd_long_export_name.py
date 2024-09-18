import socket

from avocado.utils import process
from virttest import error_context, qemu_storage

from provider.nbd_image_export import QemuNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Create a local file with qemu-img command
    2) Export the file in raw format with qemu-nbd,
       the length of export name is the max 4096
    3) Access the exported nbd file with qemu-image,
       3.1) export name is exactly the same as 2)
       3.2) length of export name is 4097
       3.3) length of export name is 4000
       3.4) length of export name is 4095

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _make_export_name(length):
        return (
            process.run(
                params["create_export_name_cmd"].format(length=length),
                ignore_status=True,
                shell=True,
            )
            .stdout.decode()
            .strip()
        )

    tag = params["images"].split()[0]
    params["nbd_export_name"] = _make_export_name(params["max_export_name_len"])

    nbd_export = QemuNBDExportImage(params, tag)
    nbd_export.export_image()

    nbd_image_tag = params["nbd_image_tag"]
    nbd_image_params = params.object_params(nbd_image_tag)
    localhost = socket.gethostname()
    nbd_image_params["nbd_server"] = localhost if localhost else "localhost"
    qemu_img = qemu_storage.QemuImg(nbd_image_params, None, nbd_image_tag)

    try:
        # Access image with the export name, just make sure
        # qemu-img info can access image successfully
        out = qemu_img.info()
        if "file format: raw" not in out:
            test.fail("Failed to access image, output(%s)" % out)

        # Access image with wrong export names
        for length in params["access_export_name_lens"].split():
            nbd_image_params["nbd_export_name"] = _make_export_name(length)
            qemu_img = qemu_storage.QemuImg(nbd_image_params, None, nbd_image_tag)

            try:
                out = qemu_img.info()
            except process.CmdError as e:
                if params["errmsg_check_%s" % length] not in str(e):
                    test.fail(
                        "Failed to get export name(%s) from output(%s)"
                        % (qemu_img.params["nbd_export_name"], out)
                    )
            else:
                test.fail("qemu-img should fail due to wrong export name")
    finally:
        nbd_export.stop_export()
