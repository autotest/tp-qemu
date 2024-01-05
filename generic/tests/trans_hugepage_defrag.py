import time
import os

from avocado.utils import process

from virttest import data_dir
from virttest import test_setup
from virttest import error_context
from virttest import kernel_interface
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Transparent hugepage defrag test:
    1) Copy and compile the THP defrag tool.
    2) Turn off the defrag value.
    3) Get the number of THPs allocated using the tool.
    4) Turn on the defrag in THP.
    5) Get again the number of THPs allocated using the tool, this one
       should be higher than previous one.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def change_feature_status(status, feature_path, test_config):
        """
        Turn on/off feature functionality.

        :param status: String representing status, may be 'on' or 'off'.
        :param feature_path: Path of the feature relative to THP config base.
        :param test_config: Object that keeps track of THP config state.

        :raise: error.TestFail, if can't change feature status
        """

        thp = kernel_interface.SysFS(os.path.join(test_config.thp_path, feature_path),
                                     session=None)
        possible_values = [each.strip("[]") for each in thp.fs_value.split()]

        if 'yes' in possible_values:
            on_action = 'yes'
            off_action = 'no'
        elif 'madvise' in possible_values:
            on_action = 'madvise'
            off_action = 'never'
        elif '1' in possible_values or '0' in possible_values:
            on_action = '1'
            off_action = '0'
        else:
            raise ValueError("Uknown possible values for file %s: %s" %
                             (test_config.thp_path, possible_values))

        if status == 'on':
            action = on_action
        elif status == 'off':
            action = off_action

        thp.sys_fs_value = action
        time.sleep(1)

    dst_dir = params.get("dst_dir", "/var/tmp")
    test_bin = params.get("test_bin", "/var/tmp/thp_fragment")
    source_file = params.get("source_file", "thp_fragment.c")
    source_package = params.get("source_package", "thp_fragment.tar.gz")
    host_path = utils_misc.get_path(data_dir.get_deps_dir('thp_defrag_tool'),
                                    source_package)
    copy_cmd = "cp -rf %s %s" % (host_path, dst_dir)
    if process.system(copy_cmd, ignore_status=True, shell=True) != 0:
        test.fail("Failed on copying the tool package!")
    extract_cmd = "cd %s; tar xzvf %s" % (dst_dir, source_package)
    if process.system(extract_cmd, ignore_status=True, shell=True) != 0:
        test.fail("Failed extracting the tool package: %s" % source_package)
    build_cmd = "cd %s; gcc -lrt %s -o %s" % (dst_dir,
                                              source_file,
                                              test_bin)
    error_context.context("Build binary file '%s'" % test_bin, test.log.info)
    if process.run(build_cmd, ignore_status=True, shell=True).exit_status != 0:
        test.fail("Failed building the the tool binary: %s" % test_bin)
    test_config = test_setup.TransparentHugePageConfig(test, params, env)
    test.log.info("Defrag test start")

    error_context.context("deactivating khugepaged defrag functionality",
                          test.log.info)
    change_feature_status("off", "khugepaged/defrag", test_config)
    change_feature_status("off", "defrag", test_config)

    thps_defrag_off = int(process.getoutput(test_bin, shell=True).split()[1])
    test.log.debug("THPs allocated with defrag off: %d" % thps_defrag_off)

    error_context.context("activating khugepaged defrag functionality",
                          test.log.info)
    change_feature_status("on", "khugepaged/defrag", test_config)
    change_feature_status("on", "defrag", test_config)

    thps_defrag_on = int(process.getoutput(test_bin, shell=True).split()[1])
    test.log.debug("THPs allocated with defrag on: %d" % thps_defrag_on)

    if thps_defrag_off >= thps_defrag_on:
        test.fail("No memory defragmentation on host: "
                  "%s THPs before turning "
                  "khugepaged defrag on, %s after it" %
                  (thps_defrag_off, thps_defrag_on))
    test.log.info("Defrag test succeeded")
