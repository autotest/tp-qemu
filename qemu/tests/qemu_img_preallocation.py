import re
import json
import timeit
import logging

from virttest import data_dir
from virttest import qemu_storage


def is_time_correct(prealloc_time):
    """
    Check if other preallocation mode is faster then full mode.

    :param prealloc_time: dict contains mode and its duration
    """
    for v in prealloc_time.values():
        if prealloc_time.get("full") < v:
            return False
    return True


def is_qcow2_preallocated(image):
    """
    Check if qcow2 image is preallocated.

    :param image: QemuImg object
    """
    res = json.loads(image.map(output="json"))
    return all(d["data"] is True for d in res)


def is_raw_preallocated(image):
    """
    Check if raw image is preallocated.

    :param image: QemuImg object
    """
    regex = r"disk size: (\d+\.?\d*\s*\w?)"
    match = re.search(regex, image.info())
    if match:
        return (match.group(1) == image.size)
    return False


is_preallocated = {"qcow2": is_qcow2_preallocated,
                   "raw": is_raw_preallocated}


def run(test, params, env):
    """
    Qemu img preallocation test:

    1. create qemu image with different preallocation mode
    2. verify creation time
    3. verify image is preallocated

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    prealloc_time = {}
    for image in params["images"].split():
        image_params = params.object_params(image)

        image = qemu_storage.QemuImg(
            image_params, data_dir.get_data_dir(), image)

        start = timeit.default_timer()
        image.create(image_params)
        duration = timeit.default_timer() - start
        mode = image_params["preallocated"]
        prealloc_time.update({mode: duration})
        logging.debug('Create image with %s mode, Time: %s.'
                      % (mode, duration))
        if not is_time_correct(prealloc_time):
            test.fail("Other preallocation mode is faster then full mode.")

        if not is_preallocated[image_params["image_format"]](image):
            test.fail("Failed to preallocation image using %s mode" % mode)
