import logging
import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test to guest-available hugepage sizes with explicit parameter.
    Steps:
    1) There are two options, with/without mem backing file,
       if without mem backing, ignore the step 3.
    2) System setup hugepages on host.
    3) Mount this hugepage to /mnt/kvm_hugepage.
    4) Boot up guest options with different cap-hpt-max-page-size,
       and there are two modes with kvm or tcg.
    5) Check output parameter don't include Hugepagesize,
       when the cap-hpt-max-page-size is 64k.
    6) Check output parameter the Hugepagesize is 16384,
       when the cap-hpt-max-page-size is 16M.

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    def _check_meminfo(key):
        meminfo = session.cmd_output("grep %s /proc/meminfo" % key)
        actual_value = re.search(r'\d{4,}', meminfo)
        return actual_value.group(0) if actual_value else ""

    timeout = params.get_numeric("login_timeout", 240)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Check output Hugepage size.", logging.info)
    if _check_meminfo("Hugepagesize") != params["expected_value"]:
        test.fail("The hugepage size doesn't match, "
                  "please check meminfo: %s " % _check_meminfo("Huge"))
