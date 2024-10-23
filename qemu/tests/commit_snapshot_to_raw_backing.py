import json

from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


def run(test, params, env):
    """
    Commit a qcow2 snapshot to a raw backing image.

    1. create an external qcow2v2/qcow2v3 snapshot
       based on a raw image
    2. boot the guest from the snapshot
    3. create a file in the snapshot disk, calculate its md5sum
    4. shut the guest down
    5. commit the snapshot to the raw backing image with various cache mode,
        and check whether the snapshot file emptied
    6. boot the guest from the raw image and check whether the
        file's md5sum stays same
    7. check the snapshot

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

    file = params["guest_file_name"]
    gen = generate_base_snapshot_pair(params["image_chain"])
    base, snapshot = next(gen)
    base_img, _ = _get_img_obj_and_params(base)
    sn_img, sn_img_params = _get_img_obj_and_params(snapshot)

    test.log.info("Create a snapshot %s based on %s.", snapshot, base)
    # workaround to assign system disk's image_name to image_name_image1
    params["image_name_image1"] = params["image_name"]
    sn_qit = QemuImgTest(test, params, env, snapshot)
    sn_qit.create_snapshot()
    _verify_qemu_img_info(
        sn_img.info(output="json"), base_img.image_format, base_img.image_filename
    )

    test.log.info(
        "Boot a guest up from snapshot image: %s, and create a" " file %s on the disk.",
        snapshot,
        file,
    )
    sn_qit.start_vm()
    md5 = sn_qit.save_file(file)
    test.log.info("Got %s's md5 %s from the snapshot image disk.", file, md5)
    sn_qit.destroy_vm()

    cache_mode = params.get("cache_mode")
    if cache_mode:
        test.log.info(
            "Commit snapshot image %s back to %s with cache mode %s.",
            snapshot,
            base,
            cache_mode,
        )
    else:
        test.log.info("Commit snapshot image %s back to %s.", snapshot, base)

    size_check = params.get("snapshot_size_check_after_commit") == "yes"
    if size_check:
        org_size = json.loads(sn_img.info(output="json"))["actual-size"]
    sn_img.commit(cache_mode=cache_mode)

    if size_check:
        remain_size = json.loads(sn_img.info(output="json"))["actual-size"]

        # Verify the snapshot file whether emptied after committing
        test.log.info("Verify the snapshot file whether emptied after committing")
        commit_size = org_size - remain_size
        dd_size = eval(params["dd_total_size"])
        if commit_size >= dd_size:
            test.log.info("The snapshot file was emptied!")
        else:
            test.fail("The snapshot file was not emptied, check pls!")

    base_qit = QemuImgTest(test, params, env, base)
    base_qit.start_vm()
    if not base_qit.check_file(file, md5):
        test.fail(
            "The file %s's md5 on base image and" " snapshot file are different." % file
        )
    base_qit.destroy_vm()

    test.log.info("Check image %s.", snapshot)
    sn_img.check_image(sn_img_params, data_dir.get_data_dir())

    for qit in (base_qit, sn_qit):
        qit.clean()
