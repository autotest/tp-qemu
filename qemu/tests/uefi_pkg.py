import re
import json
import logging

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Verify descriptor meta-files after ovmf package installation on the host:
    1) Check edk2-ovmf package has been installed already.
    2) Qurey file list on edk2-ovmf package.
    3) Make sure the descriptor meta-files will be in file list.
       2 or 3 files in total.
       For rhel7: 50-ovmf-sb.json, 60-ovmf.json
       For rhel8 and rhel9: 40-edk2-ovmf-sb.json, 50-edk2-ovmf.json
       If it supports SEV-ES on rhel8 and rhel9, there are 3 files in total.
       40-edk2-ovmf-sb.json, 50-edk2-ovmf.json and 50-edk2-ovmf-cc.json
    4) Check the JSON files internally.
       check that the "filename" elements in both files point to valid files.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_element(filename, file_list):
        """
        check 'filename' element point to a valid file

        :param filename: 'filename' element
        :param file_list: query files command output
        """
        err_str = "The 'filename' element in meta-file point to an "
        err_str += "invalid file. The invalid file is '%s'" % filename
        test.assertIn(filename, file_list, err_str)

    query_package = params["query_package"]
    error_context.context("Check edk2-ovmf package has been "
                          "installed already", logging.info)
    status, output = process.getstatusoutput(query_package,
                                             ignore_status=True,
                                             shell=True)
    if status:
        test.error("Please install edk2-ovmf package on host.")
    package_name = params["ovmf_package_name"]
    ovmf_package = re.findall(package_name, output, re.S)
    if not ovmf_package:
        test.error("Not found right edk2-ovmf package on host. "
                   "The actual output is '%s'" % output)
    query_files = params["query_files"] % ovmf_package[0]
    file_suffix = params["file_suffix"]
    meta_files = []
    output = process.getoutput(query_files, shell=True)
    for line in output.splitlines():
        if line.endswith(file_suffix):
            meta_files.append(line)
    if len(meta_files) > int(params["number_of_files"]):
        test.fail("The number of JSON files should be less than or "
                  "equal to %s. The actual file list is %s",
                  params["number_of_files"], meta_files)
    error_context.context("Check the 'filename' elements in both json"
                          " files point to valid files.", logging.info)
    for meta_file in meta_files:
        with open(meta_file, "r") as f:
            content = json.load(f)
        filename = content["mapping"]["executable"]["filename"]
        check_element(filename, output)
        filename = content["mapping"]["nvram-template"]["filename"]
        check_element(filename, output)
