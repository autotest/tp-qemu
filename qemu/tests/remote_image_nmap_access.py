import socket

from avocado.utils import process
from virttest import error_context

from provider.nbd_image_export import QemuNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Create a local raw file with qemu-img
    2) Export the file in raw format with qemu-nbd
    3) Scan the port with nmap

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
    nbd_export.export_image()

    h = socket.gethostname()
    params["nbd_server_%s" % params["nbd_image_tag"]] = h if h else "localhost"
    nmap_cmd = params["nmap_cmd"].format(
        localhost=params["nbd_server_%s" % params["nbd_image_tag"]]
    )
    try:
        result = process.run(nmap_cmd, ignore_status=True, shell=True)
        if result.exit_status != 0:
            test.fail("Failed to execute nmap, error: %s" % result.stderr.decode())

        nbd_export.list_exported_image(
            params["nbd_image_tag"], params.object_params(params["nbd_image_tag"])
        )

        if params.get("msg_check"):
            if params["msg_check"] not in result.stdout.decode().strip():
                test.fail(
                    "Failed to read message(%s) from output(%s)"
                    % (params["msg_check"], result.stderr.decode())
                )
    finally:
        nbd_export.stop_export()
