import json
import re

from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    'qemu-img check' should report the end offset of the image.
    1. Create a test qcow2 image.
    2. Check there is image end offset and the value with both "humam"
        and "json" output.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _check_result(key, offset, output):
        """Check the keywords and the value from the output."""
        if key not in output or int(offset) != int(output[key]):
            test.fail("The keyword/value is no correct. Check please.")

    report = params["images"]
    root_dir = data_dir.get_data_dir()
    report = QemuImg(params.object_params(report), root_dir, report)
    offset = params["image_end_offset"]
    human_key = params["human_key"]
    json_key = params["json_key"]

    test.log.info("Create the test image file.")
    report.create(report.params)

    # 'qemu-img check' the image and check the output info.
    check_result = report.check(report.params, root_dir, output="human").stdout.decode()
    if not check_result:
        test.error("There is no output of check command, check please.")
    test.log.debug("The check output with human output format: %s", check_result)
    result_dict = dict(re.findall(r"(.+):\s(.+)", check_result))
    _check_result(human_key, offset, result_dict)

    check_result = report.check(report.params, root_dir, output="json").stdout.decode()
    if not check_result:
        test.error("There is no output of check command, check please.")
    test.log.debug("The check output with json output format: %s", check_result)
    _check_result(json_key, offset, json.loads(check_result))
