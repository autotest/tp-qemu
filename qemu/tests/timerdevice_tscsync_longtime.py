import os
import re

from avocado.utils import process
from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Timer device check TSC synchronity for long time test:

    1) Check for an appropriate clocksource on host.
    2) Check host has more than one cpu socket.
    3) Boot the guest with specified cpu socket.
    4) Copy time-warp-test.c to guest.
    5) Compile the time-warp-test.c.
    6) Run time-warp-test for minimum 4 hours.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    error_context.context("Check for an appropriate clocksource on host", test.log.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if "tsc" not in process.getoutput(host_cmd):
        test.cancel("Host must use 'tsc' clocksource")

    error_context.context("Check host has more than one cpu socket", test.log.info)
    host_socket_cnt_cmd = params["host_socket_cnt_cmd"]
    if process.system_output(host_socket_cnt_cmd, shell=True).strip() == "1":
        test.cancel("Host must have more than 1 socket")

    error_context.context("Boot the guest with one cpu socket", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

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

    error_context.context("Run time-warp-test for minimum 4 hours", test.log.info)
    test_run_timeout = int(params.get("test_run_timeout", 14400))
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
