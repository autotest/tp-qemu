from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    1. Convert to a target image
    2. Boot up a guest from the target file

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    src_image = params["images"]
    tgt_image = params["convert_target"]
    img_dir = data_dir.get_data_dir()

    vdi_image_url = params["vdi_image_address"]
    vdi_image_download_cmd = "wget -P %s/images %s" % (img_dir, vdi_image_url)
    process.system(vdi_image_download_cmd)

    for format in ("qcow2", "raw"):
        params["image_format_convert"] = format
        # Convert the source image to target
        source = QemuImg(params.object_params(src_image), img_dir, src_image)
        target = QemuImg(params.object_params(tgt_image), img_dir, tgt_image)
        fail_on((process.CmdError,))(source.convert)(source.params, img_dir)

        # Boot from the target image
        try:
            img_utils.boot_vm_with_images(test, params, env, (tgt_image,))
        finally:
            target.remove()
