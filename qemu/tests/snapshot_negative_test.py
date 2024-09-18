import re

from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Negative test.
    Verify that qemu-img supports to check the options used for
    creating external snapshot, and raise accurate error when
    specifying a wrong option.
    1. It should be failed to create the snapshot when specifying
       a wrong format for backing file.
    2. It should be failed to create the snapshot when specifying
       a non-existing backing file.
    3. It should be failed to create the snapshot when specifying
       an empty string for backing file.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _check_command(cmds):
        """run the command and check the output"""
        cmds = cmds.split(";")
        for qemu_img_cmd in cmds:
            if qemu_img_cmd_agrs:
                qemu_img_cmd %= qemu_img_cmd_agrs
            cmd_result = process.run(qemu_img_cmd, ignore_status=True, shell=True)
            if not re.search(err_info, cmd_result.stderr.decode(), re.I | re.M):
                test.fail(
                    "Failed to get error information. The actual error "
                    "information is %s." % cmd_result.stderr.decode()
                )

    def run_cmd_with_incorrect_format():
        cmds = params.get("cmd_with_incorrect_format")
        _check_command(cmds)

    def run_cmd_with_non_existing_backing_file():
        cmds = params.get("cmd_with_non_existing_backing_file")
        _check_command(cmds)

    def run_cmd_with_empty_string_for_backing_file():
        cmds = params.get("cmd_with_empty_string_for_backing_file")
        _check_command(cmds)

    qemu_img_cmd_agrs = ""
    image_stg = params["images"]
    if image_stg == "stg":
        root_dir = data_dir.get_data_dir()
        stg = QemuImg(params.object_params(image_stg), root_dir, image_stg)
        stg.create(stg.params)
        qemu_img_cmd_agrs = stg.image_filename
    err_info = params["err_info"]
    test_scenario = params["test_scenario"]
    locals()[test_scenario]()
