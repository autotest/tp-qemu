import json

from avocado.utils import process
from virttest import data_dir, utils_numeric
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


def run(test, params, env):
    """
    Verify it can successfully convert a enlarged snapshot.

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _compare_images(img1, img2):
        """Compare two qemu images are identical or not."""
        test.log.info("Compare two images are identical.")
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
        output = process.system_output(" ".join(cmd)).decode()
        if "Images are identical" not in output:
            test.fail(
                "%s and %s are not identical."
                % (img1.image_filename, img2.image_filename)
            )

    def _create_external_snapshot(tag):
        """Create an external snapshot based on tag."""
        test.log.info("Create external snapshot %s.", tag)
        qit = QemuImgTest(test, params, env, tag)
        qit.create_snapshot()

    def _verify_backing_file(output, backing_tag):
        """Verify backing file is as expected."""
        if backing_tag is None:
            return
        backing_param = params.object_params(backing_tag)
        backing = QemuImg(backing_param, img_root_dir, backing_tag)
        if backing.image_filename not in json.loads(output)["backing-filename"]:
            test.fail("Backing file is not correct.")

    def _qemu_img_info(tag, backing_tag=None):
        """Run qemu info to given image."""
        img_param = params.object_params(tag)
        img = QemuImg(img_param, img_root_dir, tag)
        output = img.info(output="json")
        _verify_backing_file(output, backing_tag)
        return img

    def _verify_resize(img):
        """Verify the image size is as expected after resize."""
        img_size = json.loads(img.info(output="json"))["virtual-size"]
        sign = -1 if "-" in params["sn1_size_change"] else 1
        expected_size = (
            int(utils_numeric.normalize_data_size(params["image_size"], "B"))
            + int(utils_numeric.normalize_data_size(params["sn1_size_change"], "B"))
        ) * sign
        test.log.info(
            "Verify the size of  %s is %s.", img.image_filename, expected_size
        )
        if img_size != expected_size:
            test.fail(
                "Got image virtual size: %s, should be: %s." % (img_size, expected_size)
            )

    gen = generate_base_snapshot_pair(params["image_chain"])
    img_root_dir = data_dir.get_data_dir()

    base, sn1 = next(gen)
    _create_external_snapshot(sn1)
    img_sn1 = _qemu_img_info(sn1, base)
    img_sn1.resize(params["sn1_size_change"])
    _verify_resize(img_sn1)

    sn1, sn2 = next(gen)
    _create_external_snapshot(sn2)
    img_sn2 = _qemu_img_info(sn2, sn1)
    img_sn2.convert(params.object_params(sn2), img_root_dir)

    img_converted = _qemu_img_info("converted")
    _compare_images(img_sn2, img_converted)
