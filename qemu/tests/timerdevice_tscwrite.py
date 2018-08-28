import logging

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Timer device tscwrite test:

    1) Check for an appropriate clocksource on host.
    2) Boot the guest.
    3) Download and compile the newest msr-tools.
    4) Execute cmd in guest.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    error_context.context("Check for an appropriate clocksource on host",
                          logging.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if "tsc" not in process.system_output(host_cmd):
        test.cancel("Host must use 'tsc' clocksource")

    error_context.context("Boot the guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Download and compile the newest msr-tools",
                          logging.info)
    msr_tools_install_cmd = params["msr_tools_install_cmd"]
    session.cmd(msr_tools_install_cmd)

    error_context.context("Execute cmd in guest", logging.info)
    cmd = "dmesg -c > /dev/null"
    session.cmd(cmd)

    date_cmd = "strace date 2>&1 | egrep 'clock_gettime|gettimeofday' | wc -l"
    output = session.cmd(date_cmd)
    if '0' not in output:
        test.fail("Test failed before run msr tools. Output: '%s'" % output)

    msr_tools_cmd = params["msr_tools_cmd"]
    session.cmd(msr_tools_cmd)

    cmd = "dmesg"
    session.cmd(cmd)

    output = session.cmd(date_cmd)
    if "1" not in output:
        test.fail("Test failed after run msr tools. Output: '%s'" % output)
