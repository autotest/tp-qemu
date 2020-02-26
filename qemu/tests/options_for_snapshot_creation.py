import logging

from avocado.core import exceptions

from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest
from qemu.tests.qemu_disk_img import generate_base_snapshot_pair


def run(test, params, env):
    """
    Creating snapshot files with different options.
    1. Create a raw base image.
    2. Create snapshot files based on the base image with different options,
    and check there is no error.

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    gen = generate_base_snapshot_pair(params["image_chain"])
    base_img, snapshot = next(gen)
    root_dir = data_dir.get_data_dir()
    base = QemuImg(params.object_params(base_img), root_dir, base_img)
    base_filename = base.image_filename

    # Create base image.
    base.create(base.params)
    # Create snapshot file.
    QemuImgTest(test, params, env, snapshot).create_snapshot()
