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
    7) Boot up a guest with cap-hpt-max-page-size = 16M on the host with
    default huge page size

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """

    def _check_meminfo(key):
        meminfo = session.cmd_output("grep %s /proc/meminfo" % key)
        actual_value = re.search(r"\d{4,}", meminfo)
        return actual_value.group(0) if actual_value else ""

    timeout = params.get_numeric("login_timeout", 240)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Check output Hugepage size.", test.log.info)
    if _check_meminfo("Hugepagesize") != params["expected_value"]:
        test.fail(
            "The hugepage size doesn't match, "
            "please check meminfo: %s " % _check_meminfo("Huge")
        )
    # Please set 1G huge page as default huge page size on power9
    if params.get("sub_type") == "hugepage_reset":
        origin_nr = params.get("origin_nr")
        error_context.context(
            "Setup hugepage number to %s in guest" % origin_nr, test.log.info
        )
        set_hugepage_cmd = params.get("set_hugepage_cmd")
        if session.cmd_status(set_hugepage_cmd):
            test.fail("Failed to assign nr in the guest")
        check_result_cmd = params.get("check_result_cmd")
        output = session.cmd_output(check_result_cmd)
        result_value = re.search(r"\d{1,}", output).group(0)
        if result_value != origin_nr:
            test.fail(
                "Assigned nr %s doesn't match expected %s" % (result_value, origin_nr)
            )
    vm.verify_kernel_crash()
    vm.destroy()
