import re
import time

from virttest import env_process, error_context, utils_misc, utils_test

from provider import win_driver_utils, win_dump_utils


@error_context.context_aware
def check_bg_running(vm, params):
    """
    Check the backgroud test status in guest.

    :param vm: VM Object
    :param params: Dictionary with the test parameters
    :return: return True if find the driver name;
             else return False
    """
    session = vm.wait_for_login()
    target_process = params.get("target_process", "")
    if params["os_type"] == "linux":
        output = session.cmd_output_safe("pgrep -l %s" % target_process)
    else:
        list_cmd = params.get("list_cmd", "wmic process get name")
        output = session.cmd_output_safe(list_cmd, timeout=60)
    process = re.findall(target_process, output, re.M | re.I)
    session.close()
    return bool(process)


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

    def run_bg_test_simu(bg_stress_test):
        """
        Run backgroud test simultaneously with main_test.
        background test: e.g. rng_bat/balloon_test/netperf ...
        main test: e.g reboot/shutdown/stop/cont/driver_load ...

        :param bg_stress_test: Background test.
        :return: return the background case thread if it's successful;
                 else raise error.
        """
        error_context.context("Run test %s background" % bg_stress_test, test.log.info)
        stress_thread = None
        wait_time = float(params.get("wait_bg_time", 60))
        bg_stress_run_flag = params.get("bg_stress_run_flag")
        # Need to set bg_stress_run_flag in some cases to make sure all
        # necessary steps are active
        env[bg_stress_run_flag] = False
        if params.get("bg_stress_test_is_cmd", "no") == "yes":
            session = vm.wait_for_login()
            bg_stress_test = utils_misc.set_winutils_letter(session, bg_stress_test)
            session.sendline(bg_stress_test)
        else:
            stress_thread = utils_misc.InterruptedThread(
                utils_test.run_virt_sub_test,
                (test, params, env),
                {"sub_type": bg_stress_test},
            )
            stress_thread.start()

        for event in params.get("check_setup_events", "").strip().split():
            if not utils_misc.wait_for(lambda: params.get(event), 600, 0, 1):
                test.error(
                    "Background test not in ready state since haven't "
                    "received event %s" % event
                )
            # Clear event
            params[event] = False

        check_bg_timeout = float(params.get("check_bg_timeout", 120))
        if not utils_misc.wait_for(
            lambda: check_bg_running(vm, params), check_bg_timeout, 0, 1
        ):
            test.fail("Backgroud test %s is not alive!" % bg_stress_test)
        if params.get("set_bg_stress_flag", "no") == "yes":
            test.log.info("Wait %s test start", bg_stress_test)
            if not utils_misc.wait_for(
                lambda: env.get(bg_stress_run_flag), wait_time, 0, 0.5
            ):
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
            sub_type = utils_misc.set_winutils_letter(session, sub_type)
            session.cmd(sub_type, timeout=600)
            session.close()
        else:
            utils_test.run_virt_sub_test(test, params, env, sub_type)

    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    driver_running = params.get("driver_running", driver_verifier)
    timeout = int(params.get("login_timeout", 360))

    vm_name = params["main_vm"]
    if driver == "fwcfg":
        win_dump_utils.set_vm_for_dump(test, params)
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, test.log.info)

    if params["os_type"] == "windows":
        session = vm.wait_for_login(timeout=timeout)
        utils_test.qemu.windrv_verify_running(session, test, driver_running)
        session = utils_test.qemu.setup_win_driver_verifier(
            session, driver_verifier, vm
        )
        session.close()
    env["bg_status"] = 0
    run_bg_flag = params.get("run_bg_flag")
    main_test = params["sub_test"]
    bg_stress_test = params["run_bgstress"]
    wait_time = float(params.get("wait_bg_time", 60))
    suppress_exception = params.get("suppress_exception", "no") == "yes"
    wait_bg_finish = params.get("wait_bg_finish", "no") == "yes"

    error_context.context(
        "Run %s %s %s" % (main_test, run_bg_flag, bg_stress_test), test.log.info
    )
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
            if wait_bg_finish:
                stress_thread.join(suppress_exception=suppress_exception)
            else:
                stress_thread.join(
                    timeout=timeout, suppress_exception=suppress_exception
                )
        if vm.is_alive():
            if driver == "vioser":
                from qemu.tests import vioser_in_use

                vioser_in_use.kill_host_serial_pid(params, vm)
            run_bg_test_sep(bg_stress_test)
    elif run_bg_flag == "after_bg_test":
        run_bg_test_sep(bg_stress_test)
        if vm.is_dead():
            vm.create(params=params)
        utils_test.run_virt_sub_test(test, params, env, main_test)
        if vm.is_alive():
            run_bg_test_sep(bg_stress_test)
    if params.get("os_type") == "windows":
        if params.get("memory_leak_check", "no") == "yes":
            win_driver_utils.memory_leak_check(vm, test, params)
