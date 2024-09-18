import os

from virttest import cpu, data_dir, env_process, error_context
from virttest.utils_test import update_boot_option

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    support Virtual SPEC_CTRL inside guest

    1. check the 'v_spec_ctrl' on supported host
    2. add guest kernel command line 'spec_store_bypass_disable=on'
    3. verify the guest sets the spec ctrl properly on all the cpus.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    flags = params["flags"]
    check_host_flags = params.get_boolean("check_host_flags")
    if check_host_flags:
        check_cpu_flags(params, flags, test)

    supported_models = params.get("supported_models", "")
    cpu_model = params.get("cpu_model")
    if not cpu_model:
        cpu_model = cpu.get_qemu_best_cpu_model(params)
    if cpu_model not in supported_models.split():
        test.cancel("'%s' doesn't support this test case" % cpu_model)

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    proc_cmdline = params["proc_cmdline"]
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()
    boot_option = params["boot_option"]
    check_output = str(session.cmd(proc_cmdline, timeout=60)).split()
    if boot_option and boot_option not in check_output:
        error_context.context("Add '%s' to guest" % boot_option, test.log.info)
        update_boot_option(vm, args_added=boot_option)
        session = vm.wait_for_login()

    test_dir = params["test_dir"]
    source_file = params["source_file"]
    src_msr = os.path.join(data_dir.get_deps_dir(), source_file)
    vm.copy_files_to(src_msr, test_dir)
    guest_dir = params["guest_dir"]
    compile_cmd = params["compile_cmd"]
    try:
        session.cmd(compile_cmd % guest_dir)
        check_msr = "cd %s && " % guest_dir + params["check_msr"]
        result = session.cmd_output(check_msr)
        nums_vcpus = session.cmd_output("grep processor /proc/cpuinfo -c")
        if result != nums_vcpus:
            test.fail("verify the guest sets the spec ctrl failed.")
    finally:
        session.cmd("rm -rf %s/msr* %s/master*" % (test_dir, test_dir))
        session.close()
        vm.verify_kernel_crash()
        if boot_option and boot_option not in check_output:
            update_boot_option(vm, args_removed=boot_option)
