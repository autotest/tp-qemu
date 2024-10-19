import os
import time

from virttest import error_context, kernel_interface, test_setup

from provider import thp_fragment_tool


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

        thp = kernel_interface.SysFS(
            os.path.join(test_config.thp_path, feature_path), session=None
        )
        possible_values = [each.strip("[]") for each in thp.fs_value.split()]

        if "yes" in possible_values:
            on_action = "yes"
            off_action = "no"
        elif "madvise" in possible_values:
            on_action = "madvise"
            off_action = "never"
        elif "1" in possible_values or "0" in possible_values:
            on_action = "1"
            off_action = "0"
        else:
            raise ValueError(
                "Uknown possible values for file %s: %s"
                % (test_config.thp_path, possible_values)
            )

        if status == "on":
            thp.sys_fs_value = on_action
        elif status == "off":
            thp.sys_fs_value = off_action

        time.sleep(1)

    thp_fragment_tool.clean()
    thp_fragment_tool.copy_tool()
    thp_fragment_tool.build_tool(test)

    test_config = test_setup.TransparentHugePageConfig(test, params, env)
    test.log.info("Defrag test start")

    error_context.context("deactivating khugepaged defrag functionality", test.log.info)
    change_feature_status("off", "khugepaged/defrag", test_config)
    change_feature_status("off", "defrag", test_config)

    thps_defrag_off = int(thp_fragment_tool.get_tool_output().split()[1])
    test.log.debug("THPs allocated with defrag off: %d", thps_defrag_off)

    error_context.context("activating khugepaged defrag functionality", test.log.info)
    change_feature_status("on", "khugepaged/defrag", test_config)
    change_feature_status("on", "defrag", test_config)

    thps_defrag_on = int(thp_fragment_tool.get_tool_output().split()[1])
    test.log.debug("THPs allocated with defrag on: %d", thps_defrag_on)

    if thps_defrag_off >= thps_defrag_on:
        test.fail(
            "No memory defragmentation on host: "
            "%s THPs before turning "
            "khugepaged defrag on, %s after it" % (thps_defrag_off, thps_defrag_on)
        )
    test.log.info("Defrag test succeeded")
    thp_fragment_tool.clean()
