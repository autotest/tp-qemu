import os
import re

from avocado.utils import process
from virttest import data_dir, error_context


@error_context.context_aware
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
    error_context.context("Check for an appropriate clocksource on host", test.log.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if "tsc" not in process.getoutput(host_cmd):
        test.cancel("Host must use 'tsc' clocksource")

    error_context.context("Boot the guest with one cpu socket", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Check the guest is using vsyscall", test.log.info)
    date_cmd = "strace date 2>&1|egrep 'clock_gettime|gettimeofday'|wc -l"
    output = session.cmd(date_cmd)
    if "0" not in output:
        test.fail("Failed to check vsyscall. Output: '%s'" % output)

    error_context.context("Copy time-warp-test.c to guest", test.log.info)
    src_file_name = os.path.join(
        data_dir.get_deps_dir(), "tsc_sync", "time-warp-test.c"
    )
    vm.copy_files_to(src_file_name, "/tmp")

    error_context.context("Compile the time-warp-test.c", test.log.info)
    cmd = "cd /tmp/;"
    cmd += " yum install -y popt-devel;"
    cmd += " rm -f time-warp-test;"
    cmd += " gcc -Wall -o time-warp-test time-warp-test.c -lrt"
    session.cmd(cmd)

    error_context.context("Run time-warp-test", test.log.info)
    test_run_timeout = int(params.get("test_run_timeout", 10))
    session.sendline("$(sleep %d; pkill time-warp-test) &" % test_run_timeout)
    cmd = "/tmp/time-warp-test"
    output = session.cmd_status_output(cmd, timeout=(test_run_timeout + 60))[1]

    re_str = r"fail:(\d+).*?fail:(\d+).*fail:(\d+)"
    fail_cnt = re.findall(re_str, output)
    if not fail_cnt:
        test.error("Could not get correct test output. Output: '%s'" % output)

    tsc_cnt, tod_cnt, clk_cnt = [int(_) for _ in fail_cnt[-1]]
    if tsc_cnt or tod_cnt or clk_cnt:
        msg = output.splitlines()[-5:]
        test.fail(
            "Get error when running time-warp-test."
            " Output (last 5 lines): '%s'" % msg
        )

    try:
        error_context.context("Switch host to hpet clocksource", test.log.info)
        cmd = "echo hpet > /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        process.system(cmd, shell=True)

        error_context.context(
            "Run time-warp-test after change the host" " clock source", test.log.info
        )
        cmd = "$(sleep %d; pkill time-warp-test) &"
        session.sendline(cmd % test_run_timeout)
        cmd = "/tmp/time-warp-test"
        output = session.cmd_status_output(cmd, timeout=(test_run_timeout + 60))[1]

        fail_cnt = re.findall(re_str, output)
        if not fail_cnt:
            test.error("Could not get correct test output." " Output: '%s'" % output)

        tsc_cnt, tod_cnt, clk_cnt = [int(_) for _ in fail_cnt[-1]]
        if tsc_cnt or tod_cnt or clk_cnt:
            msg = output.splitlines()[-5:]
            test.fail(
                "Get error when running time-warp-test."
                " Output (last 5 lines): '%s'" % msg
            )

        output = session.cmd(date_cmd)
        if "1" not in output:
            test.fail("Failed to check vsyscall. Output: '%s'" % output)
    finally:
        error_context.context("Restore host to tsc clocksource", test.log.info)
        cmd = "echo tsc > /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        try:
            process.system(cmd, shell=True)
        except Exception as detail:
            test.log.error("Failed to restore host clocksource." "Detail: %s", detail)
