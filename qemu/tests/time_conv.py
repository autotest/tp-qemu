import os
import time

from avocado.utils import process
from virttest import data_dir, storage


def run(test, params, env):
    """
    Measure qemu-img convert time
    1. Create a image with 1GiB.
    2. Create a badly fragmented file with qemu-img bench.
    3. Measure qemu-img convert time

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    image_stg = params["images"]
    root_dir = data_dir.get_data_dir()
    image_stg_name = storage.get_image_filename(
        params.object_params(image_stg), root_dir
    )
    image_secret = params.get("image_secret")
    timeout = float(params.get("timeout", 1800))
    qemu_img_bench_cmd = params["qemu_img_bench_cmd"]
    image_format = params["image_format"]
    if image_format == "qcow2" or image_format == "raw":
        process.run(
            qemu_img_bench_cmd % (image_format, image_stg_name),
            timeout=timeout,
            shell=True,
        )
    time_list = []
    qemu_img_conv_cmd = params["qemu_img_conv_cmd"]
    conv_img = os.path.join(os.path.dirname(image_stg_name), "convert.img")
    for i in range(5):
        start_time = time.time()
        if image_format == "qcow2" or image_format == "raw":
            process.run(
                qemu_img_conv_cmd
                % (image_format, image_format, image_stg_name, conv_img)
            )
        elif image_format == "luks":
            process.run(qemu_img_conv_cmd % (image_secret, image_stg_name, conv_img))
        time_conv = time.time() - start_time
        time_list.append(time_conv)
        process.run("rm -f %s" % conv_img)
    test.log.info("The time list is: %s", time_list)
    max_time = params["max_time"]
    unexpected_time = [_ for _ in time_list if float(_) > float(max_time)]
    if unexpected_time:
        test.fail("Unexpected time: %s" % unexpected_time)
