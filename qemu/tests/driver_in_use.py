import re
import time
import logging

from virttest import utils_misc
from virttest import utils_test
from virttest import error_context


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

    def run_bg_test_simu(bg_stress_test):
        """
        Run backgroud test simultaneously with main_test.
        background test: e.g. rng_bat/balloon_test/netperf ...
        main test: e.g reboot/shutdown/stop/cont/driver_load ...

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
            stress_thread = utils_misc.InterruptedThread(
                utils_test.run_virt_sub_test, (test, params, env),
                {"sub_type": bg_stress_test})
            stress_thread.start()

        for event in params.get("check_setup_events", "").strip().split():
            if not utils_misc.wait_for(lambda: params.get(event),
                                       600, 0, 1):
                test.error("Background test not in ready state since haven't "
                           "received event %s" % event)
            # Clear event
            params[event] = False

        if not utils_misc.wait_for(lambda: check_bg_running(target_process),
                                   120, 0, 1):
            test.fail("Backgroud test %s is not alive!" % bg_stress_test)
        if params.get("set_bg_stress_flag", "no") == "yes":
            logging.info("Wait %s test start" % bg_stress_test)
            if not utils_misc.wait_for(lambda: env.get(bg_stress_run_flag),
                                       wait_time, 0, 0.5):
                err = "Fail to start %s test" % bg_stress_test
                test.error(err)
        env["bg_status"] = 1
        return stress_thread

    def run_bg_test_sep(sub_type):
        """
        Run background test separately with main_test.
        background test: e.g. rng_bat/balloon_test/netperf ...
        main test: e.g. reboot/shutdown/stop/cont/driver_load ...

        :params: sub_type: Background test.
        """
        if params.get("bg_stress_test_is_cmd", "no") == "yes":
            session = vm.wait_for_login()
            sub_type = utils_misc.set_winutils_letter(
                session, sub_type)
            session.cmd(sub_type, timeout=600)
            session.close()
        else:
            utils_test.run_virt_sub_test(test, params, env, sub_type)

    driver = params["driver_name"]
    timeout = int(params.get("login_timeout", 360))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, logging.info)

    if params["os_type"] == "windows":
        session = vm.wait_for_login(timeout=timeout)
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test, driver,
                                                                timeout)
        session.close()
    env["bg_status"] = 0
    run_bg_flag = params.get("run_bg_flag")
    main_test = params["sub_test"]
    bg_stress_test = params["run_bgstress"]
    wait_time = float(params.get("wait_bg_time", 60))
    suppress_exception = params.get("suppress_exception", "no") == "yes"

    error_context.context("Run %s %s %s" % (main_test, run_bg_flag,
                                            bg_stress_test), logging.info)
    if run_bg_flag == "before_bg_test":
        utils_test.run_virt_sub_test(test, params, env, main_test)
        if vm.is_dead():
            vm.create(params=params)
        run_bg_test_sep(bg_stress_test)
    elif run_bg_flag == "during_bg_test":
        stress_thread = run_bg_test_simu(bg_stress_test)
        stop_time = time.time() + wait_time
        while time.time() < stop_time:
            if env["bg_status"] == 1:
                utils_test.run_virt_sub_test(test, params, env, main_test)
                break
        if stress_thread:
            stress_thread.join(timeout=timeout,
                               suppress_exception=suppress_exception)
        if vm.is_alive():
            run_bg_test_sep(bg_stress_test)
    elif run_bg_flag == "after_bg_test":
        run_bg_test_sep(bg_stress_test)
        if vm.is_dead():
            vm.create(params=params)
        utils_test.run_virt_sub_test(test, params, env, main_test)
