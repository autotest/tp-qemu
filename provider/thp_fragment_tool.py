"""
thp_fragment tool.

This module is meant to copy, build and execute the thp_fragment tool.
"""
import os

from avocado.utils import process

from virttest import data_dir


dst_dir = "/var/tmp"
test_bin = "/var/tmp/thp_fragment"
source_file = "thp_fragment.c"
source_package = "thp_fragment.tar.gz"


def copy_tool(test):
    host_path = os.path.join(
        data_dir.get_deps_dir("thp_defrag_tool"), source_package
    )
    copy_cmd = "cp -rf %s %s" % (host_path, dst_dir)
    if process.system(copy_cmd, ignore_status=True, shell=True) != 0:
        test.fail("Failed on copying the tool package!")


def extract_tool(test):
    extract_cmd = "cd %s; tar xzvf %s" % (dst_dir, source_package)
    if process.system(extract_cmd, ignore_status=True, shell=True) != 0:
        test.fail("Failed extracting the tool package: %s" % source_package)


def build_tool(test):
    build_cmd = "cd %s; gcc -lrt %s -o %s" % (dst_dir, source_file, test_bin)
    test.log.info("Build binary file '%s'" % test_bin)
    if process.run(build_cmd, ignore_status=True, shell=True).exit_status != 0:
        test.fail("Failed building the the tool binary: %s" % test_bin)


def execute_tool(test):
    copy_tool(test)
    extract_tool(test)
    build_tool(test)
    process.run(test_bin, shell=True)


def get_tool_output():
    return process.getoutput(test_bin, shell=True)
