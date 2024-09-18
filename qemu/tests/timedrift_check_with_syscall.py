import os

import aexpect
from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Time clock offset check test (only for Linux guest):

    1) boot guest with '-rtc base=utc,clock=host,driftfix=slew'
    2) build binary 'clktest' in guest
    3) check clock offset with ./clktest

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    check_timeout = int(params.get("check_timeout", "600"))
    tmp_dir = params.get("tmp_dir", "/tmp")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_cmd = params.get("test_cmd", "./clktest")
    if session.cmd_status("test -x %s" % test_cmd):
        src_dir = os.path.join(data_dir.get_deps_dir(), "timedrift")
        src_file = os.path.join(src_dir, "clktest.c")
        dst_file = os.path.join(tmp_dir, "clktest.c")
        error_context.context(
            "transfer '%s' to guest('%s')" % (src_file, dst_file), test.log.info
        )
        vm.copy_files_to(src_file, tmp_dir, timeout=120)

        build_cmd = params.get("build_cmd", "gcc -lrt clktest.c -o clktest")
        error_context.context("build binary file 'clktest'", test.log.info)
        session.cmd(build_cmd)

    error_context.context("check clock offset via `clktest`", test.log.info)
    test.log.info("set check timeout to %s seconds", check_timeout)
    try:
        session.cmd_output(test_cmd, timeout=check_timeout)
    except aexpect.ShellTimeoutError as msg:
        if "Interval is" in msg.output:
            test.fail(msg.output)
        pass
