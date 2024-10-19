from virttest import env_process
from virttest.tests import unattended_install


def run(test, params, env):
    """
    Unattended install test:
    1) Starts a VM with an appropriated setup to start an unattended OS install.
    2) Wait until the install reports to the install watcher its end.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    params["cpu_model_flags"] = ""
    unattended_install.run(test, params, env)
    vm = env.get_vm(params.get("main_vm"))
    vm.destroy()

    params["cdroms"] = "winutils"
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params.get("main_vm"))
    session = vm.wait_for_login()

    session = vm.reboot(session)
    session.close()
