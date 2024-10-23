from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest


def run(test, params, env):
    """
    qemu-img convert a raw image to qcow2.

    1. boot a guest up with an initial raw image
    2. create a file on the initial image disk, calculate its md5sum
    3. shut the guest down
    4. convert initial raw image to a qcow2 image tgt
       using different compat or cache mode
    5. compare two images with strict mode option off/on (optional)
    6. boot a guest with the tgt and check whether the
       file's md5sum stays same
    7. check image tgt

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def _get_img_obj_and_params(tag):
        """Get an QemuImg object and its params based on the tag."""
        img_param = params.object_params(tag)
        img = QemuImg(img_param, data_dir.get_data_dir(), tag)
        return img, img_param

    def _compare_images(img1, img2, strict=False):
        """Compare two qemu images are identical or not."""
        test.log.info("Compare two images, strict mode: %s.", strict)
        cmd = [
            img1.image_cmd,
            "compare",
            "-f",
            img1.image_format,
            "-F",
            img2.image_format,
            img1.image_filename,
            img2.image_filename,
        ]
        if strict:
            cmd.insert(2, "-s")
        res = process.run(" ".join(cmd), ignore_status=True)
        if strict:
            if res.exit_status != 1 and "block status mismatch" not in res.stdout_text:
                test.fail("qemu-img compare strict mode error.")
        else:
            if res.exit_status != 0:
                test.fail("qemu-img compare error: %s." % res.stderr_text)
            if "Images are identical" not in res.stdout_text:
                test.fail(
                    "%s and %s are not identical."
                    % (img1.image_filename, img2.image_filename)
                )

    file = params["guest_file_name"]
    initial_tag = params["images"].split()[0]
    c_tag = params["convert_target"]

    test.log.info(
        "Boot a guest up from initial image: %s, and create a" " file %s on the disk.",
        initial_tag,
        file,
    )
    base_qit = QemuImgTest(test, params, env, initial_tag)
    base_qit.start_vm()
    md5 = base_qit.save_file(file)
    test.log.info("Got %s's md5 %s from the initial image disk.", file, md5)
    base_qit.destroy_vm()

    cache_mode = params.get("cache_mode")
    if cache_mode:
        test.log.info(
            "Convert initial image %s to %s with cache mode %s.",
            initial_tag,
            c_tag,
            cache_mode,
        )
    else:
        test.log.info("Convert initial image %s to %s", initial_tag, c_tag)
    img, img_param = _get_img_obj_and_params(initial_tag)
    img.convert(img_param, data_dir.get_data_dir(), cache_mode)

    tgt, tgt_img_param = _get_img_obj_and_params(c_tag)

    if params.get("compare_image", "no") == "yes":
        for strict in (False, True):
            _compare_images(img, tgt, strict=strict)

    c_qit = QemuImgTest(test, params, env, c_tag)
    c_qit.start_vm()
    if not c_qit.check_file(file, md5):
        test.fail(
            "The file %s's md5 on initial image and"
            " target file are different." % file
        )
    c_qit.destroy_vm()

    test.log.info("Check image %s.", c_tag)
    tgt.check_image(tgt_img_param, data_dir.get_data_dir())
    tgt.remove()

    for qit in (base_qit, c_qit):
        qit.clean()
