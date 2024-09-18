import re

from avocado.utils import process
from virttest import data_dir, storage


def run(test, params, env):
    """
    Check file fragmentation.
    1. Create a raw image with 10GiB.
    2. Create a badly fragmented file with qemu-img bench.
    3. Check file fragmentation. The extents should less than 10000.
       With 1 MiB extents, the theoretical maximum for a 10 GiB image
       is 10000 extents (10000 * 1 MiB = 10 GiB)

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    image_stg = params["images"]
    root_dir = data_dir.get_data_dir()
    image_stg_name = storage.get_image_filename(
        params.object_params(image_stg), root_dir
    )
    timeout = float(params.get("timeout", 1800))
    offset = params["offsets"].split()
    fragmentation_maximum = params["fragmentation_maximum"]
    qemu_img_bench_cmd = params["qemu_img_bench_cmd"]
    for o in offset:
        process.run(
            qemu_img_bench_cmd % (image_stg_name, o), timeout=timeout, shell=True
        )
    check_fragmentation_cmd = params["check_fragmentation_cmd"] % image_stg_name
    cmd_result = process.run(check_fragmentation_cmd, shell=True)
    extents_number_pattern = params["extents_number_pattern"]
    fragmentation_maximum = int(params["fragmentation_maximum"])
    extents_number = re.search(extents_number_pattern, cmd_result.stdout.decode())
    if not extents_number:
        test.fail(
            "Failed to get extents number. "
            "The output is '%s'." % cmd_result.stdout.decode()
        )
    if int(extents_number.group(1)) >= fragmentation_maximum:
        test.fail(
            "The extents should less than %s, the actual result is %s."
            % (fragmentation_maximum, extents_number.group(1))
        )
