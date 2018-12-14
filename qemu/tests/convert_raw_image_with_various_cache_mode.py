import logging
import json

from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest


def run(test, params, env):
    """
    qemu-img convert a raw image to qcow2 with various cache mode.

    1. boot a guest up from an initial raw image
    2. create a file on the initial image disk, calculate its md5sum
    3. shut the guest down
    4. convert the initial raw image the qcow2 target
    5. boot a guest up from  the target and check whether the
       file's md5sum stays same

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    def _get_img_obj_and_params(tag):
        """Get an QemuImg object and its params based on the tag."""
        img_param = params.object_params(tag)
        img = QemuImg(img_param, data_dir.get_data_dir(), tag)
        return img, img_param

    def _verify_qemu_img_info(output, img):
        """Verify qemu-img info output for this case."""
        logging.info("Verify the target's file information.")
        res = json.loads(output)
        if (res["filename"] != img.image_filename or
                res["format"] != img.image_format):
            test.fail("Target's information is not correct.")

    file = params["guest_file_name"]
    initial_tag = params["images"].split()[0]
    c_tag = params["image_convert"]

    logging.info("Boot a guest up from initial image: %s, and create a"
                 " file %s on the disk." % (initial_tag, file))
    base_qit = QemuImgTest(test, params, env, initial_tag)
    base_qit.start_vm()
    md5 = base_qit.save_file(file)
    logging.info("Got %s's md5 %s from the initial image disk." % (file, md5))
    base_qit.destroy_vm()

    logging.info("Convert initial image %s to %s with cache mode: %s." %
                 (initial_tag, c_tag, params["cache_mode"]))
    img, img_param = _get_img_obj_and_params(initial_tag)
    img.convert(params.object_params(
        c_tag), data_dir.get_data_dir(), params["cache_mode"])

    tgt = {"image_name_%s" % c_tag: params["convert_name_%s" % c_tag],
           "image_format_%s" % c_tag: params["convert_format_%s" % c_tag]}
    params.update(tgt)
    tgt, _ = _get_img_obj_and_params(c_tag)
    _verify_qemu_img_info(tgt.info(output="json"), tgt)

    c_qit = QemuImgTest(test, params, env, c_tag)
    c_qit.start_vm()
    if not c_qit.check_file(file, md5):
        test.fail("The file %s's md5 on initial image and"
                  " target file are different." % file)
    c_qit.destroy_vm()

    for qit in (base_qit, c_qit):
        qit.clean()
