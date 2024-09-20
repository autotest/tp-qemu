from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Qemu invalid parameter in qemu command line test:
    1) Try boot up guest with invalid parameters
    2) Catch the error message shows by qemu process

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    try:
        error_context.context("Start guest with invalid parameters.")
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.destroy()
    except Exception as emsg:
        error_context.context("Check guest exit status.")
        if "(core dumped)" in str(emsg):
            test.fail("Guest core dumped with invalid parameters.")
        else:
            test.log.info("Guest quit as expect: %s", str(emsg))
            return

    test.fail("Guest start normally, didn't quit as expect.")
