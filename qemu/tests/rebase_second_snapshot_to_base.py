import os
import json
import logging

from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest
from qemu.tests.qemu_disk_img import generate_base_snapshot_pair


def run(test, params, env):
    """
    Rebase a second qcow2 snapshot to a raw base file.

    1. create a qcow2 snapshot base -> sn1
    2. boot the guest from the sn1
    3. create a file in the snapshot disk,  calculate its md5sum
    4. shut the guest down
    5. create a qcow2 snapshot sn1 -> sn2
    6. rebase the sn2 to the base
    7. remove the sn1, optional
    8. boot the guest from the sn2 and check whether the
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

    def _get_compat_version():
        """Get snapshot compat version."""
        if params.get("image_extra_params") is None:
            # default compat version for now is 1.1
            return "1.1"
        return params.get("image_extra_params").split("=")[1]

    def _verify_qemu_img_info_backing_chain(output, b_fmt, b_name):
        """Verify qemu-img info output for this case."""
        logging.info("Verify snapshot's backing file information.")
        res = json.loads(output)[:-1]
        for idx, backing in enumerate(res):
            if (backing["backing-filename-format"] != b_fmt[idx] or
                    backing["backing-filename"] != b_name[idx]):
                test.fail("Backing file information is not correct,"
                          " got %s." % b_name[idx])
            compat = backing["format-specific"]["data"]["compat"]
            expected = _get_compat_version()
            if (compat != expected):
                test.fail("Snapshot's compat mode is not correct,"
                          " got %s, expected %s." % (compat, expected))

    file = params["guest_file_name"]
    gen = generate_base_snapshot_pair(params["image_chain"])
    base, sn1 = next(gen)
    base_img, _ = _get_img_obj_and_params(base)
    sn1_img, _ = _get_img_obj_and_params(sn1)

    logging.info("Create a snapshot %s based on %s." % (sn1, base))
    # workaround to assign system disk's image_name to image_name_image1
    params["image_name_image1"] = params["image_name"]
    sn1_qit = QemuImgTest(test, params, env, sn1)
    sn1_qit.create_snapshot()
    _verify_qemu_img_info_backing_chain(sn1_img.info(output="json"),
                                        [base_img.image_format],
                                        [base_img.image_filename])
    sn1_qit.start_vm()
    md5 = sn1_qit.save_file(file)
    logging.info("Got %s's md5 %s from the initial image disk." % (file, md5))
    sn1_qit.destroy_vm()

    sn1, sn2 = next(gen)
    sn2_img, sn2_img_params = _get_img_obj_and_params(sn2)
    logging.info("Create a snapshot %s based on %s." % (sn2, sn1))
    sn2_qit = QemuImgTest(test, params, env, sn2)
    sn2_qit.create_snapshot()
    _verify_qemu_img_info_backing_chain(
        sn2_img.info(output="json"),
        [sn1_img.image_format, base_img.image_format],
        [sn1_img.image_filename, base_img.image_filename])

    cache_mode = params.get("cache_mode")
    if cache_mode:
        logging.info("Rebase the snapshot %s to %s with cache %s." %
                     (sn2, base, params["cache_mode"]))
    else:
        logging.info("Rebase the snapshot %s to %s." % (sn2, base))
    sn2_img.base_image_filename = base_img.image_filename
    sn2_img.base_format = base_img.image_format
    sn2_img.rebase(sn2_img_params, cache_mode)
    _verify_qemu_img_info_backing_chain(sn2_img.info(output="json"),
                                        [base_img.image_format],
                                        [base_img.image_filename])

    if params.get("remove_sn1", "no") == "yes":
        logging.info("Remove the snapshot %s." % sn1)
        os.unlink(sn1_img.image_filename)

    sn2_qit.start_vm()
    if not sn2_qit.check_file(file, md5):
        test.fail("The file %s's md5 on initial image and"
                  " target file are different." % file)
    sn2_qit.destroy_vm()
