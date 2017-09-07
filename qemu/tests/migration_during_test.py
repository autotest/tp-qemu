from virttest import utils_test
from autotest.client.shared import utils


def run(test, params, env):
    """
    KVM migration test:
    1) Boot up guest in src
    2) Run sub test
    3) Send a migration command to the source VM and wait until it's finished.
    4) Kill off the source VM.
    5) Log into the destination VM after the migration is finished.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    try:
        bg = utils.InterruptedThread(
            utils_test.run_virt_sub_test, (test, params, env),
            {"sub_type": params["sub_test"]})
        bg.start()
        try:
            while bg.isAlive():
                vm.migrate(env=env)
        except Exception:
            bg.join()
            raise
    finally:
        session.close()
