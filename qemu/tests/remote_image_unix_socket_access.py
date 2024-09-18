from virttest import data_dir, error_context, qemu_storage, storage

from provider import qemu_img_utils as img_utils
from provider.nbd_image_export import QemuNBDExportImage


@error_context.context_aware
def run(test, params, env):
    """
    1) Clone the system image1 with qemu-img
    2) Export the cloned image with qemu-nbd(type=unix)
    3) Start VM from the exported image

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _prepare():
        test.log.info("Clone system image with qemu-img")
        result = qemu_storage.QemuImg(params, None, params["images"].split()[0]).dd(
            output=storage.get_image_filename(
                params.object_params(params["local_image_tag"]), data_dir.get_data_dir()
            ),
            bs=1024 * 1024,
        )
        if result.exit_status != 0:
            test.fail(
                "Failed to clone the system image, error: %s" % result.stderr.decode()
            )

        # Remove the image after test by avocado-vt
        # params['images'] += ' %s' % params["local_image_tag"]

    _prepare()

    # local image to be exported
    nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
    nbd_export.export_image()

    session = None
    test.log.info("Start VM from the exported image")

    try:
        # Start VM from the nbd exported image
        vm = img_utils.boot_vm_with_images(
            test, params, env, (params["nbd_image_tag"],)
        )
        session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
        if not session:
            test.fail("Failed to log into VM")
    finally:
        if session:
            session.close()
        vm.destroy()
        nbd_export.stop_export()
