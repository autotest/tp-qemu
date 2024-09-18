import random
import time

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Query balloon memory size, stop and continue vm from monitor
    1) Boot a guest with balloon enabled.
    2) Query balloon memory size from monitor
    3) Stop and continue vm from monitor
    4) Repeat step 2 and 3 several times
    5) Login guest after the test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    repeat_timeout = int(params.get("repeat_timeout", 360))
    timeout = int(params.get("login_timeout", 360))
    end_time = time.time() + repeat_timeout
    while time.time() < end_time:
        error_context.context("Query balloon memory from monitor", test.log.info)
        vm.monitor.info("balloon")
        error_context.context("Stop and continue vm from monitor", test.log.info)
        vm.monitor.cmd("stop")
        vm.monitor.cmd("cont")
        vm.verify_alive()
        time.sleep(random.randint(0, 3))

    error_context.context("Login guest after the test", test.log.info)
    session = vm.wait_for_login(timeout=timeout)
    session.close()
