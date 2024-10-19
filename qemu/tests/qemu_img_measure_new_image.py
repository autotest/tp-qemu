import json

from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img measure a new image.

    1. use qemu-img measure a certain size to get image file size benchmark
    2. create an image with preallocation=off of the certain size
    3. verify the image file size does not exceed benchmark's required size
    4. create an image with preallocation=full of the certain size
    5. verify the image file size does not exceed benchmark's
       fully-allocated size

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_img_obj_and_params(tag):
        """Get an QemuImg object and its params based on the tag."""
        img_param = params.object_params(tag)
        img = QemuImg(img_param, data_dir.get_data_dir(), tag)
        return img, img_param

    def _get_file_size(img):
        """Get the image file size of a given QemuImg object."""
        test.log.info("Get %s's file size.", img.image_filename)
        cmd = "stat -c %s {0}".format(img.image_filename)
        return int(process.system_output(cmd).decode())

    def _verify_file_size_with_benchmark(tag, file_size, key):
        """Verify image file size with the qemu-img measure benchmark."""
        test.log.info(
            "Verify the %s's size with benchmark.\n"
            "The image size %s does not exceed the benchmark '%s'"
            " size %s.",
            tag,
            file_size,
            key,
            benchmark[key],
        )
        if file_size > benchmark[key]:
            test.fail(
                "The %s's file size should not exceed benchmark '%s'"
                " size %s, got %s." % (tag, key, benchmark[key], file_size)
            )

    for tag in params["images"].split():
        img, img_param = _get_img_obj_and_params(tag)
        test.log.info("Using qemu-img measure to get the benchmark size.")
        benchmark = json.loads(
            img.measure(
                target_fmt=params["image_format"],
                size=params["image_size"],
                output="json",
            ).stdout_text
        )
        img.create(img_param)

        size = _get_file_size(img)
        if img_param["preallocated"] == "off":
            _verify_file_size_with_benchmark(tag, size, "required")
        if img_param["preallocated"] == "full":
            _verify_file_size_with_benchmark(tag, size, "fully-allocated")
