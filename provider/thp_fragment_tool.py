"""
thp_fragment tool.

This module is meant to copy, build and execute the thp_fragment tool.
"""

import os
import shutil

from avocado.utils import process
from virttest import data_dir

dst_dir = "/var/tmp"
test_bin = "/var/tmp/thp_fragment"
source_file = "thp_fragment.c"


def clean():
    process.system("rm -rf %s %s/%s" % (test_bin, dst_dir, source_file))


def copy_tool():
    host_path = os.path.join(data_dir.get_deps_dir("thp_defrag_tool"), source_file)
    shutil.copy2(host_path, dst_dir)


def build_tool(test):
    build_cmd = "cd %s; gcc -lrt %s -o %s" % (dst_dir, source_file, test_bin)
    test.log.info("Build binary file '%s'", test_bin)
    if process.system(build_cmd, ignore_status=True, shell=True) != 0:
        test.fail("Failed building the the tool binary: %s" % test_bin)


def get_tool_output():
    return process.getoutput(test_bin, ignore_status=False, shell=True)


def execute_tool(test):
    try:
        copy_tool()
        build_tool(test)
        get_tool_output()
    finally:
        clean()
