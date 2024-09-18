from avocado.utils import process
from virttest import env_process


def run(test, params, env):
    """
    Boot guest after disable ept/npt:
    1) Disable ept/npt
    2) Boot up guest
    3) Destory the guest and restore ept/npt

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    timeout = float(params.get("login_timeout", 2400))
    output = process.getoutput(params["check_status_cmd"])
    if output != params["expected_status"]:
        test.fail("Disable %s failed" % params["parameter_name"])
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    session.close()
