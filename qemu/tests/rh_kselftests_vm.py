import re

from avocado.core import exceptions
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    rh_kselftests_vm test
    1) Download the current kernel selftests RPM
    2) Install the RPM
    3) Execute the kernel selftests
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    kernel_path = params.get("kernel_path", "/tmp/kernel")
    tests_execution_cmd = params.get("tests_execution_cmd")
    whitelist = params.get("whitelist", "").split()

    session.cmd("mkdir -p %s" % kernel_path)
    kernel_version = session.cmd_output("uname -r").strip().split("+")[0]
    error_context.base_context("The kernel version: %s" % kernel_version, test.log.info)

    error_context.context("Download the kernel selftests RPM", test.log.debug)
    session.cmd("cd %s" % kernel_path)
    session.cmd(
        "brew download-build --rpm kernel-selftests-internal-%s.rpm" % kernel_version,
        240,
    )

    error_context.context("Install the RPM", test.log.debug)
    session.cmd("dnf install -y ./kernel-*")

    try:
        error_context.base_context("Execute the selftests", test.log.info)
        s, o = session.cmd_status_output(tests_execution_cmd, 180)
        test.log.info("The selftests results: %s", o)

        matches = re.search(r"SUMMARY:.+SKIP=(?P<skip>\d+) FAIL=(?P<fail>\d+)", o)

        num_failed_tests = int(matches.group("fail"))
        test.log.debug("Number of failed tests: %d", num_failed_tests)
        if num_failed_tests != 0:
            test.fail("Failed selftests found in the execution")

        num_skipped_tests = int(matches.group("skip"))
        test.log.debug("Number of skipped tests: %d", num_skipped_tests)

        skipped_list = []
        for test_name in whitelist:
            skipped_list.append(
                re.findall(r"\#.(\[SKIP\])\s.+(%s).\#.(SKIP)" % test_name, o)
            )

        if len(skipped_list) == num_skipped_tests:
            return True
        elif len(skipped_list) < num_skipped_tests:
            raise exceptions.TestWarn("Some skipped test(s) are not in the whitelist")

    finally:
        error_context.context("Cleaning kernel files", test.log.debug)
        session.cmd("rm -rf %s" % kernel_path)
        session.cmd("dnf remove -y $(rpm -q kernel-selftests-internal)")
