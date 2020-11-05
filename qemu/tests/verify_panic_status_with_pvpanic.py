import aexpect


def run(test, params, env):
    """
    Verify the QMP even with -device pvpanic when trigger crash,this case will:

    1) Start VM with pvpanic device.
    2) Check if pvpanic device exists in guest.
    3) Trigger crash in guest.
    4) Check vm status with QMP.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    stop_kdump_command = params["stop_kdump_command"]
    trigger_crash = params["trigger_crash"]
    qmp_check_info = params["qmp_check_info"]
    check_info = params.get("check_info")
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    if check_info:
        qtree_info = vm.monitor.info("qtree")
        if check_info not in qtree_info:
            test.fail("Not find pvpanic device in guest")

    try:
        session.cmd(stop_kdump_command)
        session.cmd(trigger_crash, timeout=5)
    except aexpect.ShellTimeoutError:
        pass
    else:
        test.fail("Guest should crash.")
    finally:
        output = vm.monitor.get_status()
        if qmp_check_info not in str(output):
            test.fail("Guest status is not guest-panicked")
        if session:
            session.close()
