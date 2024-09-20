import json

from virttest import data_dir, error_context, utils_numeric
from virttest.qemu_storage import QemuImg


@error_context.context_aware
def run(test, params, env):
    """
    A 'qemu-img' resize test.

    1.create a raw/qcow2/luks image
    2.change the raw/qcow2/luks image size * n
    3.verify resize * n

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _sum_size_changes(size_changes):
        """
        Sum the list of size changes.

        :param size_changes: list of size changes
        """
        res = []
        for change in size_changes:
            s = int(utils_numeric.normalize_data_size(change, "B")) * (
                -1 if "-" in change else 1
            )
            res.append(s)
        return sum(res)

    def _verify_resize_image(img_size, expected_size):
        """Verify the image size is as expected after resize."""
        test.log.info(
            "Verify the size of  %s is %s.", img.image_filename, expected_size
        )
        if img_size != expected_size:
            test.fail(
                "Got image virtual size: %s, should be: %s." % (img_size, expected_size)
            )

    def _verify_resize_disk(disk_size, expected_size):
        """
        Verify the disk size is as expected after resize.
        """
        test.log.info(
            "Verify the disk size of the image %s is %sG.",
            img.image_filename,
            expected_size,
        )
        if disk_size != expected_size:
            test.fail(
                "Got image actual size: %sG, should be: %sG."
                % (disk_size, expected_size)
            )

    def _resize(size_changes, preallocation):
        """Resize the image and verify its size."""
        for idx, size in enumerate(size_changes):
            test.log.info(
                "Resize the raw image %s %s with preallocation %s.",
                img.image_filename,
                size,
                preallocation,
            )
            shrink = True if "-" in size else False
            img.resize(size, shrink=shrink, preallocation=preallocation)

            if preallocation in ["full", "falloc"]:
                disk_size = json.loads(img.info(output="json"))["actual-size"]
                # Set the magnitude order to GiB, allow some bytes deviation
                disk_size = float(
                    utils_numeric.normalize_data_size(str(disk_size), "G")
                )
                expected_disk_size = size[1]
                _verify_resize_disk(int(disk_size), int(expected_disk_size))
            img_size = json.loads(img.info(output="json"))["virtual-size"]
            expected_size = int(
                utils_numeric.normalize_data_size(params["image_size_test"], "B")
            ) + _sum_size_changes(size_changes[: idx + 1])
            _verify_resize_image(img_size, expected_size)

    img_param = params.object_params("test")
    img = QemuImg(img_param, data_dir.get_data_dir(), "test")
    size_changes = params["size_changes"].split()
    preallocation = params.get("preallocation")

    test.log.info("Create a raw image %s.", img.image_filename)
    img.create(img_param)

    _resize(size_changes, preallocation)
