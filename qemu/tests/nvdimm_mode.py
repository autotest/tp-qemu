from virttest import error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Run nvdimm cases:
    1) Boot guest with two nvdimm devices
    2) Change the two nvdimm devices to dax mode inside guest
    3) Check if both devices are dax mode

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    if not utils_package.package_install("ndctl", session):
        test.cancel("Please install ndctl inside guest to proceed")
    create_dax_cmd = params["create_dax_cmd"]
    nvdimm_number = len(params["mem_devs"].split())
    try:
        for i in range(nvdimm_number):
            session.cmd(create_dax_cmd % i)
        output = session.cmd_output(params["ndctl_check_cmd"])
        output = eval(output)
        for item in output:
            if item["mode"] != "devdax":
                test.fail("Change both nvdimm to dax mode failed")
    finally:
        utils_package.package_remove("ndctl", session)
        session.close()
        vm.destroy()
