import os

import six
from avocado import TestError
from avocado.utils import partition as p
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Creating a raw image with large size on different file systems.
    1. Create a raw image with large size on XFS and check the output info.
    2. Setup EXT4 filesystem.
    3. Create a raw image with large size on the EXT4 file system and
    check the output info.

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    large_img = params["images"]
    root_dir = data_dir.get_data_dir()
    loop_img = os.path.join(root_dir, "loop.img")
    loop_size = int(params["loop_file_size"])
    file_sys = params["file_sys"]
    err_info = params["err_info"].split(";")

    mnt_dir = os.path.join(root_dir, "tmp")
    large = QemuImg(params.object_params(large_img), mnt_dir, large_img)

    # Setup file system env
    part = p.Partition(loop_img, loop_size=loop_size, mountpoint=mnt_dir)
    part.mkfs(file_sys)
    part.mount()

    test.log.info("Test creating an image with large size over %s.", file_sys)
    try:
        large.create(large.params)
    except TestError as err:
        for info in err_info:
            if info in six.text_type(err):
                break
        else:
            test.fail("CML failed with unexpected output: %s" % err)
    else:
        test.fail("There is no error when creating an image with large size.")
    finally:
        part.unmount()
        os.rmdir(mnt_dir)
        os.remove(loop_img)
