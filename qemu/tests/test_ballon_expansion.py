import os

from virttest import error_context
from virttest import data_dir

from avocado.utils import process


@error_context.context_aware
def run(test, params, env):
    """
    Test guest's baloon expansion.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    exec_timeout = params.get_numeric("exec_timeout")

    exec_file = params["exec_file"]
    exec_dir = os.path.join(data_dir.get_deps_dir(), exec_file)
    try:
        process.system(exec_dir, shell=True, timeout=exec_timeout,
                       ignore_status=True)
    finally:
        session.close()
        vm.verify_alive()
