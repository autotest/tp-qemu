import os
import re
import logging

from virttest import data_dir
from virttest import utils_misc
from avocado.utils import process
from avocado.core import exceptions
from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
      'thin-provisioning' functions test using sg_utils:
      1) Create image using qemu-img
      2) Convert the image and check if the speed is much faster than standard time


      :param test: QEMU test object
      :param params: Dictionary with the test parameters
      :param env: Dictionary with test environment.
      """

    standard_time = 0.4
    qemu_img_binary = utils_misc.get_qemu_img_binary(params)
    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    if not qemu_img_binary:
        raise exceptions.TestError("Can't find the command qemu-img.")

    image_create_cmd = params["create_cmd"]
    image_create_cmd = image_create_cmd % (qemu_img_binary, base_dir)
    image_convert_cmd = params["convert_cmd"]
    image_convert_cmd = image_convert_cmd % (qemu_img_binary, base_dir, base_dir)
    process.system(image_create_cmd, shell=True)
    output = process.system_output(image_convert_cmd, shell=True)
    realtime = re.search(r"real\s+\dm(.*)s", output)
    if realtime is None:
        raise exceptions.TestError("Faild to get the realtime from {}".format(output))
    realtime = float(realtime.group(1))
    logging.info("real time is : {:f}".format(realtime))
    if realtime >= standard_time:
        err = "realtime({:f}) to convert the image is a little longer than standardtime({:f})"
        raise exceptions.TestFail(err.format(realtime, standard_time))

    delete_image = params["disk_name"]
    delete_image = os.path.join(base_dir, delete_image)
    delete_convert_image = params.get("convert_disk_name")
    delete_convert_image = os.path.join(base_dir, delete_convert_image)

    process.system_output("rm -rf {:s} {:s}".format(delete_image, delete_convert_image))
