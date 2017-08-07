import re
import time
import logging
from virttest import utils_misc
from virttest import utils_test
from virttest import error_context
from autotest.client.shared import utils
from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    Driver in use test:
    1) boot guest with the device.
    2) enable and check driver verifier in guest.
    3) run subtest before / during / after background stress test.
    4) clear the driver verifier.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_bg_running(target_process):
        """
        Check the backgroud test status in guest.

        :param target_process: Background process running in guest.
        :return: return True if find the driver name;
                 else return False
        """
        session = vm.wait_for_login()
        list_cmd = params.get("list_cmd", "wmic process get name")
        output = session.cmd_output_safe(list_cmd, timeout=60)
        process = re.findall(target_process, output, re.M | re.I)
        session.close()
        return bool(process)

    def run_bg_stress_test(bg_stress_test):
        """
        Run backgroud test.

        :param bg_stress_test: Background test.
        :return: return the background case thread if it's successful;
                 else raise error.
        """
        error_context.context("Run test %s background" % bg_stress_test,
                              logging.info)
        stress_thread = None
        wait_time = float(params.get("wait_bg_time", 60))
        target_process = params.get("target_process", "")
        bg_stress_run_flag = params.get("bg_stress_run_flag")
        # Need to set bg_stress_run_flag in some cases to make sure all
        # necessary steps are active
        env[bg_stress_run_flag] = False
        if params.get("bg_stress_test_is_cmd", "no") == "yes":
            session = vm.wait_for_login()
            bg_stress_test = utils_misc.set_winutils_letter(
                session, bg_stress_test)
            session.sendline(bg_stress_test)
        else:
            stress_thread = utils.InterruptedThread(
                utils_test.run_virt_sub_test, (test, params, env),
                {"sub_type": bg_stress_test})
            stress_thread.start()
        if not utils_misc.wait_for(lambda: check_bg_running(target_process),
                                   120, 0, 1):
            raise exceptions.TestFail("Backgroud test %s is not "
                                      "alive!" % bg_stress_test)
        if params.get("set_bg_stress_flag", "no") == "yes":
            logging.info("Wait %s test start" % bg_stress_test)
            if not utils_misc.wait_for(lambda: env.get(bg_stress_run_flag),
                                       wait_time, 0, 0.5):
                err = "Fail to start %s test" % bg_stress_test
                raise exceptions.TestError(err)
        env["bg_status"] = 1
        return stress_thread

    def run_subtest(sub_type):
        """
        Run sub test. e.g. reboot / system_reset...

        :params: sub_type: Sub test.
        """
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    driver = params["driver_name"]
    timeout = int(params.get("login_timeout", 360))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, logging.info)

    if params["os_type"] == "windows":
        utils_test.qemu.setup_win_driver_verifier(driver, vm, timeout)

    env["bg_status"] = 0
    run_bg_flag = params.get("run_bg_flag")
    sub_type = params["sub_test"]
    bg_stress_test = params["run_bgstress"]
    wait_time = float(params.get("wait_bg_time", 60))
    suppress_exception = params.get("suppress_exception", "no") == "yes"

    error_context.context("Run %s %s %s" % (sub_type, run_bg_flag,
                                            bg_stress_test), logging.info)
    if run_bg_flag == "before_bg_test":
        run_subtest(sub_type)
        if vm.is_dead():
            vm.create(params=params)
        run_subtest(bg_stress_test)
    elif run_bg_flag == "during_bg_test":
        stress_thread = run_bg_stress_test(bg_stress_test)
        stop_time = time.time() + wait_time
        while time.time() < stop_time:
            if env["bg_status"] == 1:
                run_subtest(sub_type)
                break
        if stress_thread:
            stress_thread.join(timeout=timeout,
                               suppress_exception=suppress_exception)
    elif run_bg_flag == "after_bg_test":
        run_subtest(bg_stress_test)
        if vm.is_dead():
            vm.create(params=params)
        run_subtest(sub_type)
