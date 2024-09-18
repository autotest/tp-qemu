import json

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest with supported cpu-models
    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    :param boot_cpu_models: list of the all expected CPU models
    :param boot_models: list of all expected CPU models suitable with the
    current testing machine
    :param boot_model: the CPU model of booting the guest
    :param cpu_model_check_cmd: cmd of checking cpu models
    :param cpu_model_check_args: arguments of checking cpu models
    """
    boot_cpu_models = params.get_list("boot_cpu_models", delimiter=";")
    cpu_model_check_cmd = params.get("cpu_model_check_cmd")
    cpu_model_check_args = json.loads(params.get("cpu_model_check_args"))
    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    host_model = vm.monitor.cmd(cpu_model_check_cmd, cpu_model_check_args).get("model")
    host_model_name = host_model.get("name")[:-5]
    for boot_models in boot_cpu_models:
        if host_model_name in boot_models:
            boot_cpu_models = boot_cpu_models[: boot_cpu_models.index(boot_models) + 1]
            break
    vm.destroy()
    for boot_models in boot_cpu_models:
        params["boot_models"] = boot_models
        boot_models = params.get_list("boot_models", delimiter=",")
        for boot_model in boot_models:
            params["cpu_model"] = boot_model
            try:
                test.log.info("Start boot guest with cpu model: %s.", boot_model)
                vm.create(params=params)
                vm.verify_alive()
                vm.wait_for_serial_login()
                vm.destroy()
            except Exception as info:
                test.log.error("Guest failed to boot up with: %s", boot_model)
                test.fail(info)
