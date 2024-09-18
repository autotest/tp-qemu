from virttest import cpu, env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Boot latest cpu model on old host

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def start_with_model(test_model):
        """
        Start vm with tested model
        :param test_model: The model been tested
        """
        vm = None
        params["cpu_model"] = test_model
        test.log.info("Start vm with cpu model %s", test_model)
        try:
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            output = vm.process.get_output()
            if warning_text not in output:
                test.fail(
                    "Qemu should output warning for lack flags" " while it does not."
                )
        except Exception as e:
            if boot_expected == "no":
                test.log.info("Expect vm boot up failed when enforce is set.")
                if warning_text not in str(e):
                    raise
            else:
                raise
        else:
            if boot_expected == "no":
                test.fail(
                    "The vm should not boot successfully" " when cpu enforce mode is on"
                )
        finally:
            if vm and vm.is_alive():
                vm.verify_kernel_crash()
                vm.destroy()

    fd = open("/proc/cpuinfo")
    cpu_info = fd.read()
    fd.close()
    vendor = cpu.get_cpu_vendor(cpu_info)
    cpu_model_list = cpu.CPU_TYPES.get(vendor)
    latest_cpu_model = cpu_model_list[-1]
    for cpu_model in cpu_model_list:
        qemu_binary = utils_misc.get_qemu_binary(params)
        if cpu_model in cpu.get_qemu_cpu_models(qemu_binary):
            latest_cpu_model = cpu_model
            break

    host_cpu_model = cpu.get_qemu_best_cpu_model(params)
    if host_cpu_model.startswith(latest_cpu_model):
        test.cancel("The host cpu is not old enough for this test.")

    vm_name = params["main_vm"]
    warning_text = params.get("warning_text")
    boot_expected = params.get("boot_expected", "yes")
    params["start_vm"] = "yes"
    start_with_model(latest_cpu_model)
