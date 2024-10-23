from avocado.utils import cpu, process
from virttest import env_process


def run(test, params, env):
    """
    ept test:
    1) Turn off ept on host
    2) Check if reading kvm_intel parameter crash host
    3) Launch a guest
    3) Check no error in guest
    4) Restore env, turn on ept

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    if cpu.get_cpu_vendor_name() != "intel":
        test.cancel("This test is supposed to run on Intel host")

    unload_cmd = params["unload_cmd"]
    load_cmd = params["load_cmd"]
    read_cmd = params["read_cmd"]
    ept_value = process.getoutput(read_cmd % "ept")

    try:
        process.system(unload_cmd)
        process.system(load_cmd % "0")
        process.system(read_cmd % "vmentry_l1d_flush")

        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.preprocess_vm(test, params, env, vm.name)
        timeout = float(params.get("login_timeout", 240))

        vm.wait_for_login(timeout=timeout)
        vm.verify_kernel_crash()
    finally:
        vm.destroy()
        process.system(unload_cmd)
        process.system(load_cmd % ept_value)
