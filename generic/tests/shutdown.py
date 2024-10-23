import re
import time

from virttest import env_process, error_context, utils_test


@error_context.context_aware
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

    for i in range(shutdown_count):
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        error_context.base_context(
            "shutting down the VM %s/%s" % (i + 1, shutdown_count), test.log.info
        )
        if params.get("setup_runlevel") == "yes":
            error_context.context("Setup the runlevel for guest", test.log.info)
            utils_test.qemu.setup_runlevel(params, session)

        if shutdown_method == "shell":
            # Send a shutdown command to the guest's shell
            session.sendline(shutdown_command)
            error_context.context(
                "waiting VM to go down (shutdown shell cmd)", test.log.info
            )
        elif shutdown_method == "system_powerdown":
            # Sleep for a while -- give the guest a chance to finish booting
            time.sleep(sleep_time)
            # Send a system_powerdown monitor command
            vm.monitor.system_powerdown()
            error_context.context(
                "waiting VM to go down " "(system_powerdown monitor cmd)", test.log.info
            )

        if not vm.wait_for_shutdown(360):
            test.fail("Guest refuses to go down")

        if check_from_monitor and params.get("disable_shutdown") == "yes":
            check_failed = False
            vm_status = vm.monitor.get_status()
            if vm.monitor.protocol == "qmp":
                if vm_status["status"] != "shutdown":
                    check_failed = True
            else:
                if not re.findall(r"paused\s+\(shutdown\)", vm_status):
                    check_failed = True
            if check_failed:
                test.fail("Status check from monitor is: %s" % str(vm_status))
        if params.get("disable_shutdown") == "yes":
            # Quit the qemu process
            vm.destroy(gracefully=False)

        if i < shutdown_count - 1:
            session.close()
            env_process.preprocess_vm(test, params, env, params["main_vm"])
