from avocado.utils import process

from provider.nbd_image_export import QemuNBDExportImage


def run(test, params, env):
    """
    1) create a image with qemu-img
    2) Export the image with qemu-nbd(type=unix)
    3) Stop to export nbd image
    4) Repeat connect nbd image by nbdsh cmd

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def run_nbd_connect_cmd(cmd):
        result = process.run(cmd, timeout=5, ignore_status=True, shell=True)
        if result.exit_status != -15:
            test.fail(
                "Failed to connect nbd by unix socket,"
                "command error: %s" % result.stderr.decode()
            )

    # local image to be exported
    nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
    nbd_export.create_image()
    nbd_export.export_image()
    # stop/suspend export
    test.log.info("Suspend qemu-nbd to stop export:")
    try:
        nbd_export.suspend_export()
        nbd_connect_cmd = params["nbd_connect_cmd"]
        for iteration in range(5):
            run_nbd_connect_cmd(nbd_connect_cmd)
    finally:
        test.log.info("Stop export test image.")
        nbd_export.stop_export()
