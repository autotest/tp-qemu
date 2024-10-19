import aexpect
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Check the event after trigger a crash in VM

    1) boot up guest with pvpanic device
    2) setup crash_kexec_post_notifiers to 1 in VM and reboot VM
    3) check kdump server in guest
    4) trigger a crash in guest
    5) check the event

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Boot guest with pvpanic device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    check_kdump_service = params["check_kdump_service"]
    kdump_expect_status = params["kdump_expect_status"]
    setup_guest_cmd = params["setup_guest_cmd"]
    check_kexec_cmd = params["check_kexec_cmd"]
    expect_event = params["expect_event"]
    trigger_crash_cmd = params["trigger_crash_cmd"]
    check_ISA_cmd = params["check_ISA_cmd"]
    device_cmd = params["device_cmd"]

    error_context.context("Setup crash_kexec_post_notifiers=1 in guest", test.log.info)
    session.cmd(setup_guest_cmd)
    session = vm.reboot(session)
    s, o = session.cmd_status_output(check_kexec_cmd)
    if s or o == "":
        test.error("Failed to setup crash_kexec_post_notifiers in guest")

    error_context.context("Check kdump server status in guest", test.log.info)
    if not utils_misc.wait_for(
        lambda: session.cmd_output(check_kdump_service).startswith(kdump_expect_status),
        timeout=20,
        first=0.0,
        step=5.0,
    ):
        test.fail(
            "Kdump service did not reach %s status "
            "within the timeout period" % kdump_expect_status
        )

    error_context.context("Check ISA Bridge in the guest", test.log.info)
    o = session.cmd_output(check_ISA_cmd)
    device_id = o.split()[0]
    device_cmd = device_cmd % device_id
    o = session.cmd_output(device_cmd)
    if o.strip() != params["expected_cap"]:
        test.fail(
            "The capability value of the Pvpanic device is %s, " % o
            + "while %s is expected" % params["expected_cap"]
        )

    error_context.context("Trigger a crash in guest and check qmp event", test.log.info)
    try:
        session.cmd(trigger_crash_cmd, timeout=5)
    except aexpect.ShellTimeoutError:
        pass
    else:
        test.fail("Guest should crash.")
    finally:
        if vm.monitor.get_event(expect_event) is None:
            test.fail("Not found expect event: %s" % expect_event)
        if session:
            session.close()
