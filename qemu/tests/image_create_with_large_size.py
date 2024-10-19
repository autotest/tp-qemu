from avocado.core import exceptions
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Creating image with large size.
    1. Create a qcow2 image with large size and check the output info.
    2. Create a qcow2 with a normal size.
    3. Increase a large size to the qcow2 image and check the output info.

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    large_img, small_img = params["images"].split()
    root_dir = data_dir.get_data_dir()
    large = QemuImg(params.object_params(large_img), root_dir, large_img)
    small = QemuImg(params.object_params(small_img), root_dir, small_img)
    large_filename = large.image_filename
    size_increases = params["size_changes"]
    create_err_info = params["create_err_info"]
    resize_err_info = params["resize_err_info"]

    test.log.info("Test creating an image with large size.")
    try:
        large.create(large.params)
    except exceptions.TestError as err:
        if create_err_info not in str(err) or large_filename not in str(err):
            test.fail("CML failed with unexpected output: %s" % err)
    else:
        test.fail("There is no error when creating an image with large size.")

    test.log.info("Test resizing an image with large size.")
    small.create(small.params)
    result = small.resize(size_increases)
    status, output = result.exit_status, result.stderr_text
    if status == 0:
        test.fail("There is no error when resizing an image with large size.")
    elif resize_err_info not in output:
        test.fail("CML failed with unexpected output: %s" % output)
