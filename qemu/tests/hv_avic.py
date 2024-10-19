import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check corresponding CPUID entries with hv-avic flag

    1) boot the guest with hv-avic flag
    2) check the corresponding CPUID entries

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _get_rhel_major_ver():
        """
        Get host main version.
        """
        cmd = (
            "awk '/PRETTY_NAME/ {print}' /etc/os-release | awk '{print $5}' | "
            "awk -F '.' '{print $1}'"
        )
        rhel_major_ver = session.cmd_output(cmd)
        return rhel_major_ver.strip()

    def install_epel_repo():
        """
        Install required packages based on RHEL version.
        """
        repo_install_cmd = params.get("repo_install_cmd")
        if not repo_install_cmd:
            return
        rhel_major_ver = _get_rhel_major_ver()
        repo_install_cmd = repo_install_cmd % rhel_major_ver
        session.cmd_output_safe(repo_install_cmd)
        time.sleep(5)

    timeout = params.get_numeric("timeout", 360)
    cpuid_chk_cmd = params["cpuid_chk_cmd"]
    cpuid_pkg = params["cpuid_pkg"]
    check_cpuid_entry_cmd = params["check_cpuid_entry_cmd"]

    error_context.context("Boot the guest with hv-avic flag", test.log.info)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    status = session.cmd_status(cpuid_chk_cmd)
    if status:
        install_epel_repo()
        status = session.cmd_status("yum -y install %s" % cpuid_pkg, timeout=300)
        if status:
            test.error("Fail to install target cpuid")
    error_context.context(
        "Check the corresponding CPUID entries with " "the flag 'hv-avic'",
        test.log.info,
    )
    output = session.cmd_output(check_cpuid_entry_cmd)
    eax_value = output.splitlines()[-1].split()[2].split("0x")[-1]
    eax_value = bin(int(eax_value, 16)).split("0b")[-1]
    if eax_value[-4] != "0":
        test.fail("CPUID 0x40000004.EAX BIT(3) not cleared")
    if eax_value[-10] == "0":
        test.fail("CPUID 0x40000004.EAX BIT(9) not set")
