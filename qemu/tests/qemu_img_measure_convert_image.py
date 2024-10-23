import json

from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg, get_image_json


def run(test, params, env):
    """
    qemu-img measure an existed image than convert.

    1. create an image file
    2. write certain size (`write_size`) random data into the image
       through qemu-io
    3. use qemu-img measure the existed image and obtain the size benchmark
    4. convert the image to a qcow2/raw format image
    5. verify the produced image file size does not exceed benchmark's
       required size
    6. convert the image to a qcow2/raw format image with preallocation=full
    7. verify the produced image file size does not exceed benchmark's
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

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        image_filename = img.image_filename
        test.log.info("Run qemu-io %s", image_filename)
        if img.image_format == "luks":
            image_secret_object = img._secret_objects[-1]
            image_json_str = get_image_json(img.tag, img.params, img.root_dir)
            image_json_str = " '%s'" % image_json_str
            image_filename = image_secret_object + image_json_str
        q = QemuIOSystem(test, params, image_filename)
        q.cmd_output(cmd, 120)

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

    img, img_param = _get_img_obj_and_params(params["images"])
    img.create(img_param)
    _qemu_io(img, "write 0 %s" % params["write_size"])

    test.log.info("Using qemu-img measure to get the benchmark size.")
    benchmark = json.loads(
        img.measure(target_fmt=params["target_format"], output="json").stdout_text
    )

    for c_tag in params["convert_tags"].split():
        img_param["convert_target"] = c_tag
        img.convert(img_param, data_dir.get_data_dir())

        cvt, cvt_img_param = _get_img_obj_and_params(c_tag)
        size = _get_file_size(cvt)
        if cvt_img_param.get("sparse_size") is None:
            _verify_file_size_with_benchmark(c_tag, size, "required")
        if cvt_img_param.get("sparse_size") == "0":
            _verify_file_size_with_benchmark(c_tag, size, "fully-allocated")
        cvt.remove()
