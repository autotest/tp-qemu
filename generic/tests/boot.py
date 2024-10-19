import time

from virttest import error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Qemu reboot test:
    1) Log into a guest
    3) Send a reboot command or a system_reset monitor command (optional)
    4) Wait until the guest is up again
    5) Log into the guest to verify it's up again

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    timeout = float(params.get("login_timeout", 240))
    serial_login = params.get("serial_login", "no") == "yes"
    vms = env.get_all_vms()
    for vm in vms:
        error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
        if serial_login:
            session = vm.wait_for_serial_login(timeout=timeout)
        else:
            session = vm.wait_for_login(timeout=timeout)
        session.close()

    if params.get("rh_perf_envsetup_script"):
        for vm in vms:
            if serial_login:
                session = vm.wait_for_serial_login(timeout=timeout)
            else:
                session = vm.wait_for_login(timeout=timeout)
            utils_test.service_setup(vm, session, test.virtdir)
            session.close()
    if params.get("reboot_method"):
        for vm in vms:
            error_context.context("Reboot guest '%s'." % vm.name, test.log.info)
            if params["reboot_method"] == "system_reset":
                time.sleep(int(params.get("sleep_before_reset", 10)))
            # Reboot the VM
            if serial_login:
                session = vm.wait_for_serial_login(timeout=timeout)
            else:
                session = vm.wait_for_login(timeout=timeout)
            for i in range(int(params.get("reboot_count", 1))):
                session = vm.reboot(
                    session, params["reboot_method"], 0, timeout, serial_login
                )
            session.close()
