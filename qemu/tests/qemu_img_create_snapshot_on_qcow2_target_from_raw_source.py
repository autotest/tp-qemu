from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


def run(test, params, env):
    """
    Create snapshot based on the target qcow2 image converted from raw image.

    1. boot a guest up with an initial raw image
    2. create a file on the initial image disk, calculate its md5sum
    3. shut the guest down
    4. convert initial raw image to a qcow2 image tgt, and check the tgt
    5. create a snapshot based on tgt
    6. boot a guest from the snapshot and check whether the
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

    file = params["guest_file_name"]
    initial_tag = params["images"].split()[0]
    c_tag = params["convert_target"]

    test.log.info(
        "Boot a guest up with initial image: %s, and create a" " file %s on the disk.",
        initial_tag,
        file,
    )
    base_qit = QemuImgTest(test, params, env, initial_tag)
    base_qit.start_vm()
    md5 = base_qit.save_file(file)
    test.log.info("Got %s's md5 %s from the initial image disk.", file, md5)
    base_qit.destroy_vm()

    test.log.info("Convert initial image %s to %s", initial_tag, c_tag)
    img, img_param = _get_img_obj_and_params(initial_tag)
    img.convert(img_param, data_dir.get_data_dir())

    test.log.info("Check image %s.", c_tag)
    tgt, tgt_img_param = _get_img_obj_and_params(c_tag)
    tgt.check_image(tgt_img_param, data_dir.get_data_dir())

    gen = generate_base_snapshot_pair(params["image_chain"])
    _, snapshot = next(gen)
    test.log.info("Create a snapshot %s based on %s.", snapshot, c_tag)
    sn_qit = QemuImgTest(test, params, env, snapshot)
    sn_qit.create_snapshot()
    sn_qit.start_vm()
    if not sn_qit.check_file(file, md5):
        test.fail(
            "The file %s's md5 on initial image and" " snapshot are different." % file
        )
    for qit in (base_qit, sn_qit):
        qit.clean()
