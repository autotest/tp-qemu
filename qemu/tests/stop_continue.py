import time

from virttest import error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Suspend a running Virtual Machine and verify its state.

    1) Boot the vm
    2) Do preparation operation (Optional)
    3) Start a background process (Optional)
    4) Stop the VM
    5) Verify the status of VM is 'paused'
    6) Verify the session has no response
    7) Resume the VM
    8) Verify the status of VM is 'running'
    9) Re-login the guest
    10) Do check operation (Optional)
    11) Do clean operation (Optional)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=login_timeout)
    session_bg = None

    start_bg_process = params.get("start_bg_process")
    try:
        prepare_op = params.get("prepare_op")
        if prepare_op:
            error_context.context(
                "Do preparation operation: '%s'" % prepare_op, test.log.info
            )
            op_timeout = float(params.get("prepare_op_timeout", 60))
            session.cmd(prepare_op, timeout=op_timeout)

        if start_bg_process:
            bg_cmd = params.get("bg_cmd")
            error_context.context(
                "Start a background process: '%s'" % bg_cmd, test.log.info
            )
            session_bg = vm.wait_for_login(timeout=login_timeout)
            bg_cmd_timeout = float(params.get("bg_cmd_timeout", 240))
            args = (bg_cmd, bg_cmd_timeout)

            bg = utils_test.BackgroundTest(session_bg.cmd, args)
            bg.start()

        error_context.base_context("Stop the VM", test.log.info)
        vm.pause()
        error_context.context("Verify the status of VM is 'paused'", test.log.info)
        vm.verify_status("paused")

        error_context.context("Verify the session has no response", test.log.info)
        if session.is_responsive():
            msg = "Session is still responsive after stop"
            test.log.error(msg)
            test.fail(msg)
        session.close()
        time.sleep(float(params.get("pause_time", 0)))
        error_context.base_context("Resume the VM", test.log.info)
        vm.resume()
        error_context.context("Verify the status of VM is 'running'", test.log.info)
        vm.verify_status("running")

        error_context.context("Re-login the guest", test.log.info)
        session = vm.wait_for_login(timeout=login_timeout)

        if start_bg_process:
            if bg:
                bg.join()

        check_op = params.get("check_op")
        if check_op:
            error_context.context("Do check operation: '%s'" % check_op, test.log.info)
            op_timeout = float(params.get("check_op_timeout", 60))
            s, o = session.cmd_status_output(check_op, timeout=op_timeout)
            if s != 0:
                test.fail(
                    "Something wrong after stop continue, "
                    "check command report: %s" % o
                )
    finally:
        try:
            clean_op = params.get("clean_op")
            if clean_op:
                error_context.context(
                    "Do clean operation: '%s'" % clean_op, test.log.info
                )
                # session close if exception raised, so get renew a session
                # to do cleanup step.
                session = vm.wait_for_login(timeout=login_timeout)
                op_timeout = float(params.get("clean_op_timeout", 60))
                session.cmd(clean_op, timeout=op_timeout, ignore_all_errors=True)
            session.close()
            if session_bg:
                session_bg.close()
        except Exception as details:
            test.log.warning("Exception occur when clean test environment: %s", details)
