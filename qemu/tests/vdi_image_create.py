from avocado import TestError
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    1. Create a vdi image.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    test_img = params["images"]
    root_dir = data_dir.get_data_dir()
    test_image = QemuImg(params.object_params(test_img), root_dir, test_img)
    test.log.info("Create the vdi test image file.")
    try:
        test_image.create(test_image.params)
    except TestError as err:
        test.fail("Create the vdi image failed with unexpected output: %s" % err)
