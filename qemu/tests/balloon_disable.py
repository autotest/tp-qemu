from virttest import qemu_monitor


def run(test, params, env):
    """
    KVM balloon disable test:
    1) Log into a guest
    2) Send a system monitor command (info balloon) and check return value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=float(params.get("login_timeout", 240)))
    try:
        output = vm.monitor.info("balloon")
    except qemu_monitor.QMPCmdError as e:
        output = str(e)
    if not (
        "has not been activated" in output
        or "No balloon device has been activated" in output
    ):
        test.fail("Balloon driver still on when disable it on command line")
    session.close()
