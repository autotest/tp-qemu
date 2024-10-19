from virttest import cpu, env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Get kernel src code from src rpm and run protection key tests.

    1) Download src rpm from brew
    2) Unpack src code and compile protection_keys.c
    3) Run executable file 'protection_keys'
    4) Check results

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    unsupported_models = params.get("unsupported_models", "")
    cpu_model = params.get("cpu_model", cpu.get_qemu_best_cpu_model(params))
    if cpu_model in unsupported_models.split():
        test.cancel("'%s' doesn't support this test case" % cpu_model)

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", test.log.info)
    session = vm.wait_for_login()

    guest_dir = params["guest_dir"]
    timeout = params.get_numeric("timeout")
    kernel_v = session.cmd_output("uname -r").strip()
    mkdir_cmd = session.cmd("mkdir -p %s" % guest_dir)
    src_rpm = "kernel-" + kernel_v.rsplit(".", 1)[0] + ".src.rpm"
    linux_name = "linux-" + kernel_v.rsplit(".", 1)[0]
    download_rpm_cmd = "cd %s && " % guest_dir + params["download_rpm_cmd"] % src_rpm
    uncompress_cmd_src = "cd %s && " % guest_dir + params["uncompress_cmd_src"]
    uncompress_cmd = "cd %s && " % guest_dir + params["uncompress_cmd"]
    test_dir = guest_dir + linux_name + params["test_dir"]
    compile_cmd = "cd %s && " % test_dir + params["compile_cmd"]
    run_cmd = "cd %s && " % test_dir + params["run_cmd"]

    try:
        session.cmd(mkdir_cmd)
        error_context.context("Get kernel source code", test.log.info)
        session.cmd(download_rpm_cmd, timeout=600)
        session.cmd(uncompress_cmd_src, timeout)
        session.cmd(uncompress_cmd, timeout)
        session.cmd(compile_cmd, timeout)
        s, output = session.cmd_status_output(run_cmd, safe=True)
        if "done (all tests OK)" not in output:
            test.fail("Protection key test runs failed.")

        vm.verify_kernel_crash()
    finally:
        session.cmd("rm -rf %s" % guest_dir)
        session.close()
