import os
import re

from avocado.utils import cpu
from virttest import arch, error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Execute the libguestfs-test-tool unittest inside L1 guest.

    1) Launch a guest and check if libguestfs-tools is installed.
    2) Execute the libguestfs-test-tool directly launching qemu.
    3) Analyze the result of libguestfs-test-tool.
    4) Check the nested file exists(ignore on s390x).

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    kvm_module = arch.get_kvm_module_list()[-1].replace("-", "_")
    is_kvm_mode = params["nested_flag"] == "nested_flag_on"
    nested_file = os.path.join("/sys/module/", kvm_module, "parameters/nested")
    unittest_timeout = params.get_numeric("unittest_timeout")

    cpu_vendor = cpu.get_vendor()
    cpu_arch = cpu.get_arch()
    if cpu_arch == "powerpc" and int(cpu.get_family().strip("power")) < 9:
        test.cancel("Nested feature requires a POWER9 CPU")
    elif cpu_arch == "x86_64":
        flag = "vmx" if cpu_vendor == "intel" else "svm"
        params["cpu_model_flags"] = params["cpu_model_flags"].format(flag)

    params["start_vm"] = "yes"
    vm = env.get_vm(params["main_vm"])
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Check if libguestfs-tools is installed.", test.log.info)
    sm = utils_package.RemotePackageMgr(session, "libguestfs-tools")
    if not (sm.is_installed("libguestfs-tools") or sm.install()):
        test.cancel("Unable to install libguestfs-tools inside guest.")

    try:
        error_context.context(
            "Execute the libguestfs-test-tool unittest " "directly launching qemu.",
            test.log.info,
        )
        stderr_file = "/tmp/lgf_stderr"
        lgf_cmd = (
            "LIBGUESTFS_BACKEND=direct libguestfs-test-tool "
            "--timeout {} 2> {}".format(unittest_timeout, stderr_file)
        )
        lgf_s, lgf_o = session.cmd_status_output(lgf_cmd, timeout=unittest_timeout)
        test.log.debug("libguestfs-test-tool stdout:\n%s", lgf_o)
        lgf_stderr = session.cmd_output("cat " + stderr_file)
        lgf_tcg = re.search("Back to tcg accelerator", lgf_stderr)

        error_context.context(
            "Analyze the libguestfs-test-tool test result.", test.log.info
        )
        fail_msg = (
            "the exit status is non-zero"
            if lgf_s
            else "back to tcg accelerator"
            if lgf_tcg and is_kvm_mode
            else ""
        )
        if fail_msg:
            test.log.debug("libguestfs-test-tool stderr:\n%s", lgf_stderr)
            test.fail("libguestfs-test-tool execution failed due to: %s. " % fail_msg)

        if cpu_arch != "s390":
            error_context.context("Check the nested file status.", test.log.info)
            file_s, file_o = session.cmd_status_output("cat " + nested_file)
            if re.match(r"[1Y]", file_o) and is_kvm_mode:
                test.log.info(
                    "Guest runs with nested flag, the nested feature has "
                    "been enabled."
                )
            elif file_s == 1 and not is_kvm_mode:
                test.log.info(
                    "Guest runs without nested flag, so the nested file "
                    "does not exist."
                )
            else:
                test.log.error("Nested file status: %s, output: %s", file_s, file_o)
                test.fail("Getting the status of nested file has unexpected " "result.")
    finally:
        session.cmd("rm -f " + stderr_file, ignore_all_errors=True)
        session.close()
