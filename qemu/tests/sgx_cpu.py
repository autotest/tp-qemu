from virttest import error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu sgx cpu test:
    1. Boot sgx VM
    2. Check sgx guest cpuid with sub-features
    3. Check sgx guest corresponding CPUID entries

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start sgx cpu test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    try:
        verify_dmesg()

        # Set up guest environment
        cpuid_pkg = params.get("cpuid_pkg")
        if session.cmd_status("rpm -qa|grep %s" % cpuid_pkg):
            try:
                session.cmd_output_safe(params.get("repo_install_cmd"))
                session.cmd_status("yum -y install %s" % cpuid_pkg)
            except Exception:
                test.cancel(
                    "Fail to install package cpuid, please retest" "this case again."
                )

        error_context.context("Check the sgx CPUID features", test.log.info)
        check_cpuid_entry_cmd = params.get("cpuid_entry_cmd")
        sgx_features_list = params.get("sgx_features").split()
        for i in sgx_features_list:
            cmd = params.get("check_cpuid_sgx_cmd").format(sgx_cpu_features=i)
            if session.cmd_status(cmd):
                test.fail("Fail to verify sgx feature %s " % i)
        if params.get("cpuid_entry_cmd"):
            error_context.context(
                "Check the corresponding CPUID entries with" "sgx cpu flags",
                test.log.info,
            )
            output = session.cmd_output(check_cpuid_entry_cmd)
            eax_value = output.splitlines()[-1].split()[2].split("0x")[-1]
            eax_value = bin(int(eax_value, 16)).split("0b")[-1]
            if eax_value[-5] != "1":
                test.fail("CPUID 0x12.0x1.EAX bit 4 is 0")
    finally:
        session.close()
    vm.destroy()
