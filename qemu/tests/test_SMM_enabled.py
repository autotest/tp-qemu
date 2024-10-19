import os
import time

from virttest import data_dir, env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test SMM enabled by developer's script
    1) Boot qemu with test binary smm_int_window.flat
    2) get test results, should pass without error

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    source_file = params["source_file"]
    src_test_binary = os.path.join(data_dir.get_deps_dir(), source_file)
    error_msg = params["error_msg"]
    params["kernel"] = src_test_binary

    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    time.sleep(10)
    output = vm.process.get_output()
    if error_msg in output:
        test.fail("Test failed because of qemu core dump!")
