import logging
import time
import random

import aexpect

from virttest import error_context
from virttest import utils_test
from virttest import utils_misc


def setup_test_environment(test, params, vm, session):
    """
    Setup environment configuration modification.

    Operation includds disable kdumpservice, configure
    unknown_nmi_panic for linux, or modify the register value for
    windows, in order to trigger crash.

    :param test: test object
    :param params: parameters
    :vm: target vm
    :session: session created by loggin the vm
    """
    timeout = int(params.get("timeout", 360))
    if params.get("os_type") == "linux":
        # stop kdump service and enable unknown_nmi_panic
        setup_cmds = [params.get("set_kdump_cmd"),
                      params.get("set_panic_cmd")]
    else:
        # modify the register for windows
        setup_cmds = [params.get("set_panic_cmd")]
    for cmd in setup_cmds:
        status, output = session.cmd_status_output(cmd, timeout)
        if status:
            test.error("Command '%s' failed, status: %s, output: %s" %
                       (cmd, status, output))
    if params.get("os_type") == "windows":
        vm.reboot(session, timeout=timeout)


def check_qmp_events(vm, event_name, timeout=360):
    """
    Check whether certain qmp event appeared in vm.

    :param vm: target virtual machine
    :param event_name: target event name, such as 'GUEST_PANICKED'
    :param timeout: check time
    """
    end_time = time.time() + timeout
    logging.info("Try to get qmp events %s in %s seconds!",
                 event_name, timeout)
    while time.time() < end_time:
        if vm.monitor.get_event(event_name):
            logging.info("Receive qmp %s event notification", event_name)
            vm.monitor.clear_event(event_name)
            return True
        time.sleep(5)
    return False


def trigger_crash(test, vm, params):
    """
    Trigger system crash with certain method.

    :param vm: target vm
    :parma params: test params
    """
    crash_method = params["crash_method"]
    if crash_method == "nmi":
        vm.monitor.nmi()
    elif crash_method in ("usb_keyboard", "ps2_keyboard"):
        crash_key1 = params["crash_key1"]
        crash_key2 = params["crash_key2"]
        vm.monitor.press_release_key(crash_key1)
        vm.send_key(crash_key2)
        vm.send_key(crash_key2)
    elif crash_method == "notmyfault_app":
        timeout = int(params.get("timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        cmd = params["notmyfault_cmd"] % random.randint(1, 8)
        notmyfault_cmd = utils_misc.set_winutils_letter(session, cmd)
        try:
            status, output = session.cmd_status_output(cmd=notmyfault_cmd,
                                                       timeout=timeout)
            if status:
                test.error("Command '%s' failed, status: %s, output: %s" %
                           (cmd, status, output))
        # notmyfault_app triggers BSOD of the guest, and it terminates
        # qemu process, so sometimes, it can not get the status of the cmd.
        except (aexpect.ShellTimeoutError,
                aexpect.ShellProcessTerminatedError,
                aexpect.ShellStatusError):
            pass
    else:
        test.cancel("Crash trigger method %s not supported, "
                    "please check cfg file for mistake." % crash_method)


@error_context.context_aware
def run(test, params, env):
    """
    Pvpanic test.

    1) Log into the guest
    2) Check if the driver is installed and verified (only for win)
    3) Stop kdump service and modify unknown_nmi_panic(for linux)
       or modify register value(for win)
    4) Trigger a crash by nmi, keyboard or notmyfault app
    5) Check the event in qmp

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    timeout = int(params.get("timeout", 360))
    event_check = params.get("event_check", "GUEST_PANICKED")
    error_context.context("Boot guest with pvpanic device", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    if params.get("os_type") == "windows":
        error_context.context("Check if the driver is installed and "
                              "verified", logging.info)
        driver_name = params.get("driver_name", "pvpanic")
        session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                test,
                                                                driver_name,
                                                                timeout)

    if params["crash_method"] != "notmyfault_app":
        error_context.context("Setup crash evironment for test", logging.info)
        setup_test_environment(test, params, vm, session)

    error_context.context("Trigger crash", logging.info)
    trigger_crash(test, vm, params)

    error_context.context("Check the panic event in qmp", logging.info)
    if not check_qmp_events(vm, event_check, timeout):
        test.fail("Did not receive qmp %s event notification"
                  % event_check)
