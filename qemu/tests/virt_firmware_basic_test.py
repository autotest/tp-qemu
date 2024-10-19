import os
import re
import shutil
import sys

import six
from avocado.utils import git, process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test check for virt-firmware.

    The tests contain test-dump, test-vars,
    test-sigdb and test-unittest.

    If the package 'python3-virt-firmware-tests' has been installed,
    run the scripts under '/usr/share/python-virt-firmware/tests'.
    Otherwise, clone the virt-firmware repo and run the following scripts.

    test-dump:
        tests/test-dump.sh
    test-vars:
        tests/test-vars.sh
    test-sigdb:
        tests/test-sigdb.sh
    peutils has been dropped from version 1.6,
    so adding 'test-pe' to blacklist
    test-pe:
        tests/test-pe.sh
    test-unittest:
        python3 tests/tests.py

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    query_cmd = params["cmd_queried_test_package"]
    status = process.getstatusoutput(query_cmd, ignore_status=True, shell=True)[0]
    if status:
        test.log.info(
            "Package 'python3-virt-firmware-tests' "
            "has not been installed. "
            "Run the test with virt firmware repo."
        )
        virt_firmware_dirname = params["virt_firmware_repo_dst_dir"]
        virt_firmware_repo_addr = params["virt_firmware_repo_addr"]
        test_file_black_list = params["test_file_black_list"].split()
        if os.path.exists(virt_firmware_dirname):
            shutil.rmtree(virt_firmware_dirname, ignore_errors=True)
        try:
            git.get_repo(
                uri=virt_firmware_repo_addr, destination_dir=virt_firmware_dirname
            )
        except Exception as e:
            test.error(
                "Failed to clone the virt-firmware repo,"
                "the error message is '%s'." % six.text_type(e)
            )
    else:
        test.log.info("Run the test with package " "'python3-virt-firmware-tests'.")
        virt_firmware_dirname = params["virt_firmware_test_package_dir"]
        test_file_black_list = []
    test_file_pattern = params["test_file_pattern"]
    test_dirname = os.path.join(virt_firmware_dirname, "tests")
    for file_name in os.listdir(test_dirname):
        if re.search(test_file_pattern, file_name, re.I):
            if file_name in test_file_black_list:
                continue
            test_file = os.path.join(test_dirname, file_name)
            if file_name.endswith("py"):
                test_cmd = sys.executable + " " + test_file + " 2>&1"
            else:
                test_cmd = params["shell_cmd"] % test_file
            error_context.context(
                "Test check with command '%s'." % test_cmd, test.log.info
            )
            status, output = process.getstatusoutput(
                test_cmd, ignore_status=True, shell=True
            )
            if status:
                test.fail(
                    "Failed to run '%s', the error message is '%s'" % (test_cmd, output)
                )
            error_context.context(
                "The output of command '%s':\n%s" % (test_cmd, output), test.log.info
            )
    if "test_file" not in locals():
        test.error("Not found test file in '%s', please check it." % test_dirname)
