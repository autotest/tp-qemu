import random
import re

from virttest import error_context, utils_misc, utils_test

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestLinux, BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Qemu balloon device stress test:
    1) boot guest with balloon device
    2) enable driver verifier in guest (Windows only)
    3) run stress in background repeatly
    4) balloon memory in monitor in loop

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_bg_running():
        """
        Check the background test status in guest.
        :return: return True if find the process name; otherwise False
        """
        if params["os_type"] == "windows":
            list_cmd = params.get("list_cmd", "wmic process get name")
            output = session.cmd_output_safe(list_cmd, timeout=60)
            process = re.findall("mplayer", output, re.M | re.I)
            return bool(process)
        else:
            return stress_bg.app_running()

    error_context.context("Boot guest with balloon device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    if params["os_type"] == "windows":
        driver_name = params["driver_name"]
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )
        balloon_test = BallooningTestWin(test, params, env)
    else:
        balloon_test = BallooningTestLinux(test, params, env)

    error_context.context("Run stress background", test.log.info)
    stress_test = params.get("stress_test")
    if params["os_type"] == "windows":
        utils_test.run_virt_sub_test(test, params, env, stress_test)
        if not utils_misc.wait_for(
            check_bg_running,
            first=2.0,
            text="wait for stress app to start",
            step=1.0,
            timeout=60,
        ):
            test.error("Run stress background failed")
    else:
        stress_bg = utils_test.VMStress(vm, "stress", params)
        stress_bg.load_stress_tool()

    repeat_times = int(params.get("repeat_times", 1000))
    min_sz, max_sz = balloon_test.get_memory_boundary()

    error_context.context("balloon vm memory in loop", test.log.info)
    try:
        for i in range(1, int(repeat_times + 1)):
            test.log.info("repeat times: %d", i)
            balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
            if not check_bg_running():
                test.error("Background stress process is not alive")
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        if session:
            session.close()
