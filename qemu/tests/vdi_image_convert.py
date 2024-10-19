from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    1. Convert images between raw and vdi.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError:
            test.error("qemu-io to '%s' failed." % img.image_filename)

    src_image = params["images"]
    tgt_image = params["convert_target"]
    img_dir = data_dir.get_data_dir()

    source = QemuImg(params.object_params(src_image), img_dir, src_image)
    _qemu_io(source, "write -P 1 0 %s" % params["write_size"])

    fail_on((process.CmdError,))(source.convert)(source.params, img_dir)

    params["images"] += " " + tgt_image
