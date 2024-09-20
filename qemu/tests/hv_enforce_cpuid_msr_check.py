from virttest import error_context

from provider import qemu_img_utils


@error_context.context_aware
def run(test, params, env):
    """
    Add 'hv_enforce_cpuid' option to try to use a forbidden feature.
    1. Boot the guest with following hv flags.
    eg: -cpu host,hv-relaxed,hv-enforce-cpuid
    2. Run command rdmsr 0x40000002 in guest( 0x40000002 should NOT be read).
    3. Check the results.
    4. Boot the guest without 'hv-enforce-cpuid'.
    5. Run command rdmsr 0x40000002 in guest( 0x40000002 should be read).
    6. Check the results.

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _set_env(session):
        """
        Set up the system environment before test

        param session: the session of vm
        """
        # install repo
        session.cmd_output_safe(params.get("repo_install_cmd"))
        # install msr-tools
        if session.cmd_status(params.get("msr_install_cmd")):
            test.error("Failed to install msr-tools")

    def _run_msr_tools(session):
        """
        run msr-tools cmd

        params session: the session of vm
        return res: the result of output
        """
        session.cmd_output_safe(params.get("modprobe_cmd"), timeout=360)
        res = session.cmd_output_safe(params.get("rdmsr_cmd"), timeout=360)
        return res

    error_context.context("The case starts...", test.log.info)
    error_context.context("Boot the guest with 'hv-enforce-cpuid ", test.log.info)
    session = None
    origin_flags = params["cpu_model_flags"]
    try:
        params["cpu_model_flags"] = (
            origin_flags + "," + params.get("cpu_model_flags_with_enforce")
        )
        vm = qemu_img_utils.boot_vm_with_images(test, params, env)
        session = vm.wait_for_login(timeout=360)
        _set_env(session)
        res_with_hv = _run_msr_tools(session)
        res_with_hv = res_with_hv.split("\n")[0]
        if res_with_hv != params.get("expect_result_with_enforce"):
            test.fail(
                "The output from the case of cpu with hv-enforce-cpuid "
                "was NOT expected." + " The tuple in return is : %s" % res_with_hv
            )
    finally:
        vm.destroy()

    error_context.context("Boot the guest without 'hv-enforce-cpuid ", test.log.info)
    try:
        params["cpu_model_flags"] = (
            origin_flags + "," + params.get("cpu_model_flags_without_enforce")
        )
        vm = qemu_img_utils.boot_vm_with_images(test, params, env)
        session = vm.wait_for_login(timeout=360)
        _set_env(session)
        res_without_hv = _run_msr_tools(session)
        res_without_hv = res_without_hv.split("\n")[0]
        if res_without_hv != params.get("expect_result_without_enforce"):
            test.fail(
                "The output from the case of cpu without "
                "hv-enforce-cpuid was NOT expected."
                + " The tuple in return is : %s"
                % res_without_hv
            )
    finally:
        vm.destroy()
