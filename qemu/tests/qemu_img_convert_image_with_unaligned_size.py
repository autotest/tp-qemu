from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img supports convert images with unaligned size.

    1. create source image via truncate, and  write 10k "1" into
       the source image via qemu-io
    2. convert the source image to target, check whether there is error

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError:
            test.fail("qemu-io to '%s' failed." % img.image_filename)

    src_image = params["images"]
    tgt_image = params["convert_target"]
    img_dir = data_dir.get_data_dir()

    source = QemuImg(params.object_params(src_image), img_dir, src_image)
    with open(source.image_filename, mode="wb") as fd:
        fd.truncate(int(params["truncate_size"]))
    _qemu_io(source, "write -P 1 0 %s" % params["write_size"])

    fail_on((process.CmdError,))(source.convert)(
        source.params, img_dir, cache_mode="none", source_cache_mode="none"
    )

    params["images"] += " " + tgt_image
