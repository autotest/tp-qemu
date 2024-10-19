import re

import aexpect
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test hdparm setting on linux guest os. This case will:
    1) Set/record parameters value of hard disk to low performance status.
    2) Perform device/cache read timings then record the results.
    3) Set/record parameters value of hard disk to high performance status.
    4) Perform device/cache read timings then compare two results.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def check_setting_result(set_cmd, timeout):
        params = re.findall("(-[a-zA-Z])([0-9]*)", set_cmd)
        disk = re.findall(r"(\/+[a-z]*\/[a-z]*$)", set_cmd)[0]
        unsupport_param = 0
        for param, value in params:
            check_value = True
            cmd = "hdparm %s %s" % (param, disk)
            (s, output) = session.cmd_status_output(cmd, timeout)
            failed_count = len(re.findall("failed:", output))
            ignore_count = len(re.findall(ignore_string, output))
            if failed_count > ignore_count:
                test.error(
                    "Fail to get %s parameter value. "
                    "Output is:\n%s" % (param, output.strip())
                )
            else:
                check_value = False
                unsupport_param += 1
                test.log.warning("Disk %s not support parameter %s", disk, param)
            if check_value and value not in output:
                test.fail("Fail to set %s parameter to value: %s" % (param, value))
        if len(params) == unsupport_param:
            test.cancel("All parameters are not supported. Skip the test")

    def perform_read_timing(disk, timeout, num=5):
        results = 0
        for i in range(num):
            cmd = params["device_cache_read_cmd"] % disk
            (s, output) = session.cmd_status_output(cmd, timeout)
            if s != 0:
                test.fail(
                    "Fail to perform device/cache read"
                    " timings \nOutput is: %s\n" % output
                )
            test.log.info(
                "Output of device/cache read timing check (%s of %s):", i + 1, num
            )
            for line in output.strip().splitlines():
                test.log.info(line)
            (result, unit) = re.findall("= *([0-9]*.+[0-9]*) ([a-zA-Z]*)", output)[1]
            if unit == "kB":
                result = float(result) / 1024.0
            results += float(result)
        return results / num

    ignore_string = params.get("ignore_string")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    try:
        timeout = float(params.get("cmd_timeout", 60))
        cmd = params["get_disk_cmd"]
        output = session.cmd(cmd)
        disk = output.strip()

        error_context.context("Setting hard disk to lower performance")
        cmd = params["low_status_cmd"] % disk
        try:
            session.cmd(cmd, timeout)
        except aexpect.ShellCmdError as err:
            failed_count = len(re.findall("failed:", err.output))
            ignore_count = len(re.findall(ignore_string, err.output))
            if failed_count > ignore_count:
                test.error(
                    "Fail to setting hard disk to lower " "performance. Output is:%s",
                    err.output,
                )

        error_context.context(
            "Checking hard disk keyval under " "lower performance settings"
        )
        check_setting_result(cmd, timeout)
        low_result = perform_read_timing(disk, timeout)
        test.log.info(
            "Average buffered disk read speed under low performance "
            "settings: %.2f MB/sec",
            low_result,
        )

        error_context.context("Setting hard disk to higher performance")
        cmd = params["high_status_cmd"] % disk
        try:
            session.cmd(cmd, timeout)
        except aexpect.ShellCmdError as err:
            failed_count = len(re.findall("failed:", err.output))
            ignore_count = len(re.findall(ignore_string, err.output))
            if failed_count > ignore_count:
                test.error(
                    "Fail to setting hard disk to higher " "performance. Output is:%s",
                    err.output,
                )

        error_context.context(
            "Checking hard disk keyval under " "higher performance settings"
        )
        check_setting_result(cmd, timeout)
        high_result = perform_read_timing(disk, timeout)
        test.log.info(
            "Average buffered disk read speed under high performance "
            "settings: %.2f MB/sec",
            high_result,
        )

        if not float(high_result) > float(low_result):
            test.fail("High performance setting does not increase read speed")

    finally:
        if session:
            session.close()
