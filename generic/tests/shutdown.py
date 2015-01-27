import time
import logging
import re
from autotest.client.shared import error
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    KVM shutdown test:
    1) Log into a guest
    2) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    3) Wait until the guest is down

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    timeout = int(params.get("login_timeout", 360))
    shutdown_count = int(params.get("shutdown_count", 1))
    shutdown_method = params.get("shutdown_method", "shell")
    sleep_time = float(params.get("sleep_before_powerdown", 10))
    shutdown_command = params.get("shutdown_command")
    check_from_monitor = params.get("check_from_monitor", "no") == "yes"

    for i in xrange(shutdown_count):
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        if len(vm.virtnet) > 0:
            session = vm.wait_for_login(timeout=timeout)
        else:
            session = vm.wait_for_serial_login(timeout=timeout)

        error.base_context("shutting down the VM %s/%s" % (i + 1,
                                                           shutdown_count),
                           logging.info)
        if params.get("setup_runlevel") == "yes":
            error.context("Setup the runlevel for guest", logging.info)
            expect_runlevel = params.get("expect_runlevel", "3")

            ori_runlevel = session.cmd("runlevel")
            ori_runlevel = re.findall("\d+", ori_runlevel)[-1]
            if ori_runlevel == expect_runlevel:
                logging.info("Guest runlevel is the same as expect.")
            else:
                session.cmd("init %s" % expect_runlevel)
                tmp_runlevel = session.cmd("runlevel")
                tmp_runlevel = re.findall("\d+", tmp_runlevel)[-1]
                if tmp_runlevel != expect_runlevel:
                    logging.warn("Failed to setup runlevel for guest")

        if shutdown_method == "shell":
            # Send a shutdown command to the guest's shell
            session.sendline(shutdown_command)
            error.context("waiting VM to go down (shutdown shell cmd)",
                          logging.info)
        elif shutdown_method == "system_powerdown":
            # Sleep for a while -- give the guest a chance to finish booting
            time.sleep(sleep_time)
            # Send a system_powerdown monitor command
            vm.monitor.cmd("system_powerdown")
            error.context("waiting VM to go down "
                          "(system_powerdown monitor cmd)", logging.info)

        if not vm.wait_for_shutdown(360):
            raise error.TestFail("Guest refuses to go down")

        if check_from_monitor and params.get("disable_shutdown") == "yes":
            check_failed = False
            vm_status = vm.monitor.get_status()
            if vm.monitor.protocol == "qmp":
                if not vm_status['status'] != "shutdown":
                    check_failed = True
            else:
                if not re.findall("paused\s+\(shutdown\)", vm_status):
                    check_failed = True
            if check_failed:
                raise error.TestFail("Status check from monitor "
                                     "is: %s" % str(vm_status))
        if params.get("disable_shutdown") == "yes":
            # Quit the qemu process
            vm.destroy(gracefully=False)

        if i < shutdown_count - 1:
            session.close()
            env_process.preprocess_vm(test, params, env, params["main_vm"])
