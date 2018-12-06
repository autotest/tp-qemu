import logging
import json

from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest
from qemu.tests.qemu_disk_img import generate_base_snapshot_pair


def run(test, params, env):
    """
    Rebase a qcow2 snapshot onto no backing file.

    1. create an external qcow2v2/qcow2v3 snapshot
       based on a raw image
    2. boot the guest from the base
    3. create a file in the base disk, calculate its md5sum
    4. shut the guest down
    5. rebase the snapshot to ""(empty string) onto no backing file
    6. check the snapshot
    7. boot the guest from the snapshot and check whether the
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

    def _verify_qemu_img_info(output, b_fmt, b_name):
        """Verify qemu-img info output for this case."""
        logging.info("Verify snapshot's backing file information.")
        res = json.loads(output)
        if (res["backing-filename-format"] != b_fmt or
                res["backing-filename"] != b_name):
            test.fail("Backing file information is not correct,"
                      " got %s." % b_name)
        compat = res["format-specific"]["data"]["compat"]
        expected = _get_compat_version()
        if compat != expected:
            test.fail("Snapshot's compat mode is not correct,"
                      " got %s, expected %s." % (compat, expected))

    def _verify_no_backing_file(output):
        """Verify snapshot has no backing file for this case."""
        logging.info("Verify snapshot has no backing file after rebase.")
        for key in json.loads(output):
            if "backing" in key:
                test.fail("The snapshot has backing file after rebase.")

    file = params["guest_file_name"]
    gen = generate_base_snapshot_pair(params["image_chain"])
    base, snapshot = next(gen)
    base_img, _ = _get_img_obj_and_params(base)
    sn_img, sn_img_params = _get_img_obj_and_params(snapshot)

    logging.info("Create a snapshot %s based on %s.", snapshot, base)
    # workaround to assign system disk's image_name to image_name_image1
    params["image_name_image1"] = params["image_name"]
    sn_qit = QemuImgTest(test, params, env, snapshot)
    sn_qit.create_snapshot()
    _verify_qemu_img_info(sn_img.info(output="json"),
                          base_img.image_format, base_img.image_filename)

    logging.info("Boot a guest up from base image: %s, and create a"
                 " file %s on the disk.", base, file)
    base_qit = QemuImgTest(test, params, env, base)
    base_qit.start_vm()
    md5 = base_qit.save_file(file)
    logging.info("Got %s's md5 %s from the base image disk.", file, md5)
    base_qit.destroy_vm()

    sn_img.base_tag, sn_img.base_image_filename = ("null", "null")
    sn_img.rebase(sn_img_params)
    _verify_no_backing_file(sn_img.info(output="json"))
    sn_img.check_image(sn_img_params, data_dir.get_data_dir())

    sn_qit = QemuImgTest(test, params, env, snapshot)
    sn_qit.start_vm()
    if not sn_qit.check_file(file, md5):
        test.fail("The file %s's md5 on base image and"
                  " snapshot file are different." % file)
    sn_qit.destroy_vm()

    for qit in (base_qit, sn_qit):
        qit.clean()
