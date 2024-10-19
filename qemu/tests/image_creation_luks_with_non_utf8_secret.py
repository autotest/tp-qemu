import os
import re

from avocado.utils import process
from virttest import data_dir, utils_misc


def run(test, params, env):
    """
    Negative test.
    Luks image creation with non_utf8_secret:
    1. It should be failed to create the image.
    2. The error information should be corret.
       e.g. Data from secret sec0 is not valid UTF-8

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    image_stg_name = params["image_name_stg"]
    root_dir = data_dir.get_data_dir()
    image_stg_path = utils_misc.get_path(root_dir, image_stg_name)
    if os.path.exists(image_stg_path):
        os.remove(image_stg_path)
    err_info = params["err_info"]
    tmp_dir = data_dir.get_tmp_dir()
    non_utf8_secret_file = os.path.join(tmp_dir, "non_utf8_secret")
    non_utf8_secret = params["echo_non_utf8_secret_cmd"] % non_utf8_secret_file
    process.run(non_utf8_secret, shell=True)
    qemu_img_create_cmd = params["qemu_img_create_cmd"] % (
        non_utf8_secret_file,
        image_stg_path,
    )
    cmd_result = process.run(qemu_img_create_cmd, ignore_status=True, shell=True)
    if os.path.exists(image_stg_path):
        test.fail(
            "The image '%s' should not exist. Since created"
            " it with non_utf8_secret." % image_stg_path
        )
    if not re.search(err_info, cmd_result.stderr.decode(), re.I):
        test.fail(
            "Failed to get error information. The actual error "
            "information is %s." % cmd_result.stderr.decode()
        )
