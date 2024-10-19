import re
import time

from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check corresponding CPUID entries with hyper-v enlightenment flag

    1) boot the guest with hv flag, like hv-tlbflush-ext, hv-tlbflush-direct.
    2) check the corresponding CPUID entries
    3) boot the guest without the attahced hv flag
    4) check the corresponding CPUID entries again

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _boot_guest_with_cpu_flag(hv_flag):
        """
        Boot the guest, with param cpu_model_flags set to hv_flag

        param hv_flag: the hv flags to set to cpu

        return: the booted vm and a loggined session
        """
        params["cpu_model_flags"] = hv_flag
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login(timeout=timeout)
        return (vm, session)

    def run_cpuid_check(check_register, check_bit):
        """
        Run cpuid check.

        param check_register: CPU register, like EAX, EBX, ECX, EDX.
        Param check_bit: Check bit in cpu register, like 14 bit in EAX register.

        """
        error_context.context(
            "Check the corresponding CPUID entries with " "the flag %s" % hv_flag,
            test.log.info,
        )
        output = session.cmd_output(check_cpuid_entry_cmd)
        match = re.search(r"%s=0x([0-9a-fA-F]+)" % check_register, output)
        value = int(match.group(1), 16)
        bit_result = (value >> check_bit) & 0x01
        return bit_result

    def _get_rhel_major_ver():
        """
        Get host major version.
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
    hv_flag = params["hv_flag"]
    cpuid_chk_cmd = params["cpuid_chk_cmd"]
    cpuid_pkg = params["cpuid_pkg"]
    check_cpuid_entry_cmd = params["check_cpuid_entry_cmd"]
    check_register = params["check_register"]
    check_bit = int(params["check_bit"])
    cpu_model_flags = params["cpu_model_flags"]
    hv_flags_to_ignore = params["hv_flags_to_ignore"].split()

    error_context.context("Boot the guest with %s flag" % hv_flag, test.log.info)
    vm, session = _boot_guest_with_cpu_flag(cpu_model_flags)
    status = session.cmd_status(cpuid_chk_cmd)
    if status:
        install_epel_repo()
        status = session.cmd_status("yum -y install %s" % cpuid_pkg)
        if status:
            test.error("Fail to install target cpuid")
    if not run_cpuid_check(check_register, check_bit):
        test.fail("CPUID %s BIT(%s) does not set" % (check_register, check_bit))
    vm.graceful_shutdown(timeout=timeout)

    error_context.context("Boot the guest without %s flag" % hv_flag, test.log.info)
    without_hv_flag = ",".join(
        [_ for _ in cpu_model_flags.split(",") if _ not in hv_flags_to_ignore]
    )
    vm, session = _boot_guest_with_cpu_flag(without_hv_flag)
    if run_cpuid_check(check_register, check_bit):
        test.fail("CPUID %s BIT(%s) was set" % (check_register, check_bit))
