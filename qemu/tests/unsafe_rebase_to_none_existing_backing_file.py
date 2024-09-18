import json

from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


def run(test, params, env):
    """
    Unsafe rebase a qcow2 snapshot to a none existing the raw backing file.

    1. create a qcow2 snapshot based on a raw image with compat mode 0.10/1.1
    2. rebase the snapshot to a none exist the raw backing file
    3. check the snapshot

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
        test.log.info("Verify snapshot's backing file information.")
        res = json.loads(output)
        if res["backing-filename-format"] != b_fmt or res["backing-filename"] != b_name:
            test.fail("Backing file information is not correct," " got %s." % b_name)
        compat = res["format-specific"]["data"]["compat"]
        expected = _get_compat_version()
        if compat != expected:
            test.fail(
                "Snapshot's compat mode is not correct,"
                " got %s, expected %s." % (compat, expected)
            )

    def _verify_unsafe_rebase(img):
        """Verify qemu-img check output for this case."""
        test.log.info("Verify snapshot's unsafe check information.")
        res = process.run(
            "%s check %s" % (img.image_cmd, img.image_filename), ignore_status=True
        )
        expected = [
            "Could not open backing file",
            img.base_image_filename,
            "No such file or directory",
        ]
        for msg in expected:
            if msg not in res.stderr_text:
                test.fail("The %s should not exist." % img.base_image_filename)

    gen = generate_base_snapshot_pair(params["image_chain"])
    base, snapshot = next(gen)
    base_img, _ = _get_img_obj_and_params(base)
    sn_img, sn_img_params = _get_img_obj_and_params(snapshot)

    test.log.info("Create a snapshot %s based on %s.", snapshot, base)
    # workaround to assign system disk's image_name to image_name_image1
    params["image_name_image1"] = params["image_name"]
    QemuImgTest(test, params, env, snapshot).create_snapshot()
    _verify_qemu_img_info(
        sn_img.info(output="json"), base_img.image_format, base_img.image_filename
    )

    sn_img.base_tag = params["none_existing_image"]
    sn_img.rebase(sn_img_params)
    _verify_qemu_img_info(
        sn_img.info(output="json"), sn_img.base_format, sn_img.base_image_filename
    )

    _verify_unsafe_rebase(sn_img)
