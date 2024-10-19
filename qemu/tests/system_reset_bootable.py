import random
import time

from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    KVM reset test:
    1) Boot guest.
    2) Check the guest boot up time.(optional)
    3) Reset system by monitor command for several times. The interval time
       should can be configured by cfg file or based on the boot time get
       from step 2.
    4) Log into the guest to verify it could normally boot.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 240))
    reset_times = int(params.get("reset_times", 20))
    interval = int(params.get("reset_interval", 10))
    wait_time = int(params.get("wait_time_for_reset", 60))
    min_wait_time = int(params.get("min_wait_time", 0))
    params["start_vm"] = "yes"

    if params.get("get_boot_time") == "yes":
        error_context.context("Check guest boot up time", test.log.info)
        env_process.preprocess_vm(test, params, env, vm.name)
        vm.wait_for_login(timeout=timeout)
        bootup_time = time.time() - vm.start_time
        if params.get("reset_during_boot") == "yes":
            interval = int(bootup_time)
            wait_time = random.randint(min_wait_time, int(bootup_time))
        vm.destroy()

    error_context.context("Boot the guest", test.log.info)
    env_process.preprocess_vm(test, params, env, vm.name)
    test.log.info("Wait for %d seconds before reset", wait_time)
    time.sleep(wait_time)

    for i in range(1, reset_times + 1):
        error_context.context("Reset guest system for %s times" % i, test.log.info)

        vm.monitor.cmd("system_reset")

        interval_tmp = interval
        if params.get("fixed_interval", "yes") != "yes":
            interval_tmp = random.randint(0, interval * 1000) / 1000.0

        test.log.debug("Reset the system by monitor cmd" " after %ssecs", interval_tmp)
        time.sleep(interval_tmp)

    error_context.context("Try to login guest after reset", test.log.info)
    vm.wait_for_login(timeout=timeout)
