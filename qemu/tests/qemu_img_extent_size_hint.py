import re

from virttest import data_dir, utils_misc
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img measure a new image.

    1. create an image with default extent_size_hit
    3. check it in qemu-img info
    4. create an image with extent_size_hit in range [1M 3.5G]
    5. check it in qemu-img info
    6. create an image with extent_size_hit=0
    7. check it in qemu-img info

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _image_create():
        """Create an image."""
        image_name = params.get("images")
        img_param = params.object_params(image_name)
        img = QemuImg(img_param, data_dir.get_data_dir(), image_name)
        img.create(img_param)
        return img

    def ck_extent_size_hint(img, expect):
        """Check extent_size_hint in qemu-img info"""
        parttern = params.get("esh_pattern")
        output = img.info()
        test.log.info("Check the extent size hint from output")
        es_hint = re.findall(parttern, output)
        if es_hint:
            if es_hint[0] != expect:
                test.fail(
                    "Extent_size_hint %s is not expected value %s" % (es_hint, expect)
                )
        elif expect != "0":
            test.fail("Failed to get extent_size_hint info")

    extent_size_hints = params.get("extent_size_hints")
    for es_hint in re.split(r"\s+", extent_size_hints.strip()):
        if es_hint == "default":
            esh = params.get("esh_default", "1M")
        else:
            params["image_extent_size_hint"] = es_hint
            esh = es_hint
        esh_tmp = utils_misc.normalize_data_size(esh, "B")
        esh_expect = esh_tmp.split(".")[0]

        image = _image_create()

        test.log.info("Check extent size hint when it sets to %s", es_hint)
        ck_extent_size_hint(image, esh_expect)
