import json

from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg
from virttest.utils_numeric import normalize_data_size


def run(test, params, env):
    """
    qemu-img supports to create a raw image file.
    1. Create test image, and  write 1M "1" into
       the test image via qemu-io.
    2. Check the image virtual and actual size info.
    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError as err:
            test.fail("qemu-io to '%s' failed: %s." % (img.image_filename, err))

    def _check_img_size(img_info, defined_sizes, size_keys):
        """Check the size info of the image"""
        for defined_size, size_key in zip(defined_sizes, size_keys):
            test.log.info(
                "Check the '%s' size info of %s", size_key, source.image_filename
            )
            defined_size = normalize_data_size(defined_size, "B")
            get_size = img_info[size_key]
            if int(defined_size) != int(get_size):
                test.fail(
                    "Got unexpected size '%s', expected size is '%s'"
                    % (get_size, defined_size)
                )

    src_image = params["images"]
    img_dir = data_dir.get_data_dir()
    write_size = params["write_size"]

    source = QemuImg(params.object_params(src_image), img_dir, src_image)
    source.create(source.params)
    _qemu_io(source, "write -P 1 0 %s" % write_size)

    src_info = json.loads(source.info(output="json"))
    _check_img_size(
        src_info,
        [write_size, params["image_size_test"]],
        ["actual-size", "virtual-size"],
    )
