from virttest import error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Run nvdimm cases:
    1) Boot guest with nvdimm device backed by a host file
    2) Run redis test inside guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    error_context.context("Install dependency packages in guest", test.log.info)
    pkgs = params["depends_pkgs"].split()
    if not utils_package.package_install(pkgs, session):
        test.cancel("Install dependency packages failed")
    try:
        error_context.context("Get redis in guest", test.log.info)
        cmds = []
        cmds.append(params["get_redis"])
        cmds.append(params["get_nvml"])
        cmds.append(params["compile_nvml"])
        cmds.append(params["compile_redis"])
        for cmd in cmds:
            s, o = session.cmd_status_output(cmd, timeout=600)
            if s:
                test.error("Failed to run cmd '%s', output: %s" % (cmd, o))
        error_context.context("Run redis test in guest", test.log.info)
        s, o = session.cmd_status_output(params["run_test"], timeout=3600)
        if s:
            test.fail("Run redis test failed, output: %s" % o)
        vm.verify_kernel_crash()
    finally:
        if session:
            session.cmd_output_safe("rm -rf %s" % params["redis_dir"])
        vm.destroy()
