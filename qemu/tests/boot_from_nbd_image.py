import socket

from avocado import fail_on
from avocado.utils import process
from virttest import qemu_storage

from provider import qemu_img_utils as img_utils
from provider.nbd_image_export import QemuNBDExportImage


def run(test, params, env):
    """
    1) Create a local raw/qcow2/luks image
    2) Export it with qemu-nbd
    3) Convert remote system image to the exported nbd image
    4) Start VM from the exported image
    5) Log into VM
    """

    def _convert_image():
        source = params["images"].split()[0]
        target = params["convert_target"]
        source_params = params.object_params(source)
        target_params = params.object_params(target)
        source_image = qemu_storage.QemuImg(source_params, None, source)

        # Convert source to target
        fail_on((process.CmdError,))(source_image.convert)(
            target_params, None, skip_target_creation=True
        )

    nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
    nbd_export.create_image()
    nbd_export.export_image()

    # we only export image with local nbd server
    localhost = socket.gethostname()
    params["nbd_server_%s" % params["convert_target"]] = (
        localhost if localhost else "localhost"
    )

    vm = None
    try:
        _convert_image()
        vm = img_utils.boot_vm_with_images(
            test, params, env, (params["convert_target"],)
        )
        session = vm.wait_for_login(timeout=params.get_numeric("login_timeout", 480))
        session.close()
    finally:
        if vm:
            vm.destroy()
        nbd_export.stop_export()
