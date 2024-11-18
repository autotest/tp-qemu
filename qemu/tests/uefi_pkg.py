import json
import re

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Verify descriptor meta-files after ovmf package installation on the host:
    1) Check edk2-ovmf package has been installed already.
    2) Qurey file list on edk2-ovmf package.
    3) Make sure the descriptor meta-files will be in file list.
       For rhel7: 50-ovmf-sb.json, 60-ovmf.json
       For rhel8: 40-edk2-ovmf-sb.json, 50-edk2-ovmf.json
       If it supports SEV-ES, there are 3 files in total.
       40-edk2-ovmf-sb.json, 50-edk2-ovmf.json and 50-edk2-ovmf-cc.json
       For rhel9.0 and rhel9.1: there are 4 files in total.
       40-edk2-ovmf-sb.json, 50-edk2-ovmf.json, 50-edk2-ovmf-cc.json
       and 50-edk2-ovmf-amdsev.json
       For rhel9.2 and higher versin: there are 5 files in total.
       30-edk2-ovmf-x64-sb-enrolled.json, 40-edk2-ovmf-x64-sb.json,
       50-edk2-ovmf-x64-nosb.json, 60-edk2-ovmf-x64-amdsev.json and
       60-edk2-ovmf-x64-inteltdx.json
    4) Check the JSON files internally.
       check that the "filename" elements in both files point to valid files.
       for amdsev and inteltdx json files, check that the 'mode' is 'stateless'
       for other json files, if it has 'mode' element, check its value is
       'split'

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_element_filename(filename, file_list):
        """
        check 'filename' element point to a valid file

        :param filename: 'filename' element
        :param file_list: query files command output
        """
        err_str = "The 'filename' element in meta-file point to an "
        err_str += "invalid file. The invalid file is '%s'" % filename
        test.assertIn(filename, file_list, err_str)

    def check_element_mode(mode, expected_mode):
        """
        check 'mode' element, its value is stateless for amdsev and inteltdx.
        And because explicitly set mode = split from rhel9.3, the value of
        mode is split or stateless.

        :param mode: 'mode' element
        :param expected_mode: the expected value of 'mode' element
        """
        err_str = "The expected mode is '%s' instead of '%s'."
        test.assertTrue(mode == expected_mode, err_str % (expected_mode, mode))

    query_package = params["query_package"]
    error_context.context(
        "Check edk2-ovmf package has been " "installed already", test.log.info
    )
    status, output = process.getstatusoutput(
        query_package, ignore_status=True, shell=True
    )
    if status:
        test.error("Please install edk2-ovmf package on host.")
    package_name = params["ovmf_package_name"]
    ovmf_package = re.findall(package_name, output, re.S)
    if not ovmf_package:
        test.error(
            "Not found right edk2-ovmf package on host. "
            "The actual output is '%s'" % output
        )
    query_files = params["query_files"] % ovmf_package[0]
    file_suffix = params["file_suffix"]
    meta_files = []
    output = process.getoutput(query_files, shell=True)
    for line in output.splitlines():
        if line.endswith(file_suffix):
            meta_files.append(line)
    if len(meta_files) > int(params["number_of_files"]):
        test.fail(
            "The number of JSON files should be less than or "
            "equal to %s. The actual file list is %s",
            params["number_of_files"],
            meta_files,
        )
    error_context.context(
        "Check the 'filename' elements in both json" " files point to valid files.",
        test.log.info,
    )
    for meta_file in meta_files:
        test.log.info("Checking the meta file '%s'", meta_file)
        with open(meta_file, "r") as f:
            content = json.load(f)
        # for inteltdx with secure boot, the device type is memory
        # instead of flash
        if "memory" == content["mapping"]["device"]:
            filename = content["mapping"]["filename"]
        else:
            filename = content["mapping"]["executable"]["filename"]
        check_element_filename(filename, output)
        # for inteltdx with secure boot, just need to check binary file,
        # no vars file, skip the 'nvram-template' element checking
        # for amdsev and inteltdx without secure boot, check the 'mode'
        # element and because they don't have vars file,
        # skip the 'nvram-template' element checking
        # for other json files, if it has 'mode' element, check its
        # value is 'split'
        if "inteltdx.secboot" in filename:
            continue
        elif "amdsev" in filename or "inteltdx" in filename:
            mode = content["mapping"]["mode"]
            check_element_mode(mode, "stateless")
            continue
        elif "mode" in content["mapping"]:
            mode = content["mapping"]["mode"]
            check_element_mode(mode, "split")
        filename = content["mapping"]["nvram-template"]["filename"]
        check_element_filename(filename, output)
