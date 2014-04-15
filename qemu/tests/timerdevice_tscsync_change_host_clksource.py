import logging
import os
import re
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir, remote_build


@error.context_aware
def run(test, params, env):
    """
    Timer device check TSC synchronity after change host clocksource:

    1) Check for an appropriate clocksource on host.
    2) Boot the guest.
    3) Check the guest is using vsyscall.
    4) Copy time-warp-test.c to guest.
    5) Compile the time-warp-test.c.
    6) Switch host to hpet clocksource.
    6) Run time-warp-test.
    7) Check the guest is not using vsyscall.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    error.context("Check for an appropriate clocksource on host", logging.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if not "tsc" in utils.system_output(host_cmd):
        raise error.TestNAError("Host must use 'tsc' clocksource")

    error.context("Boot the guest with one cpu socket", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Check the guest is using vsyscall", logging.info)
    date_cmd = "strace date 2>&1|egrep 'clock_gettime|gettimeofday'|wc -l"
    output = session.cmd(date_cmd)
    if not '0' in output:
        raise error.TestFail("Failed to check vsyscall. Output: '%s'" % output)

    address = vm.get_address(0)
    source_dir = data_dir.get_deps_dir("tsc_sync")
    build_dir = params.get("build_dir", None)

    builder = remote_build.Builder(params, address, source_dir,
                                   build_dir=build_dir)

    full_build_path = builder.build()

    error.context("Run time-warp-test", logging.info)
    test_run_timeout = int(params.get("test_run_timeout", 10))
    session.sendline("$(sleep %d; pkill time-warp-test) &" % test_run_timeout)
    cmd = os.path.join(full_build_path, "time-warp-test")
    _, output = session.cmd_status_output(cmd, timeout=(test_run_timeout + 60))

    re_str = "fail:(\d+).*?fail:(\d+).*fail:(\d+)"
    fail_cnt = re.findall(re_str, output)
    if not fail_cnt:
        raise error.TestError("Could not get correct test output."
                              " Output: '%s'" % output)

    tsc_cnt, tod_cnt, clk_cnt = [int(_) for _ in fail_cnt[-1]]
    if tsc_cnt or tod_cnt or clk_cnt:
        msg = output.splitlines()[-5:]
        raise error.TestFail("Get error when running time-warp-test."
                             " Output (last 5 lines): '%s'" % msg)

    try:
        error.context("Switch host to hpet clocksource", logging.info)
        cmd = "echo hpet > /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        utils.system(cmd)

        error.context("Run time-warp-test after change the host clock source",
                      logging.info)
        cmd = "$(sleep %d; pkill time-warp-test) &"
        session.sendline(cmd % test_run_timeout)
        cmd = os.path.join(full_build_path, "time-warp-test")
        _, output = session.cmd_status_output(cmd,
                                              timeout=(test_run_timeout + 60))

        fail_cnt = re.findall(re_str, output)
        if not fail_cnt:
            raise error.TestError("Could not get correct test output."
                                  " Output: '%s'" % output)

        tsc_cnt, tod_cnt, clk_cnt = [int(_) for _ in fail_cnt[-1]]
        if tsc_cnt or tod_cnt or clk_cnt:
            msg = output.splitlines()[-5:]
            raise error.TestFail("Get error when running time-warp-test."
                                 " Output (last 5 lines): '%s'" % msg)

        output = session.cmd(date_cmd)
        if not "1" in output:
            raise error.TestFail("Failed to check vsyscall."
                                 " Output: '%s'" % output)
    finally:
        error.context("Restore host to tsc clocksource", logging.info)
        cmd = "echo tsc > /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        try:
            utils.system(cmd)
        except Exception, detail:
            logging.error("Failed to restore host clocksource."
                          "Detail: %s" % detail)
