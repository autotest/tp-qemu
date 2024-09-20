from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Fileup disk test:
    Purpose to expand the qcow2 file to its max size.
    Suggest to test rebooting vm after this test.
    1). Fillup guest disk (root mount point) using dd if=/dev/zero.
    2). Clean up big files in guest with rm command.


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session2 = vm.wait_for_serial_login(timeout=login_timeout)

    fillup_timeout = int(params.get("fillup_timeout"))
    fillup_size = int(params.get("fillup_size"))
    fill_dir = params.get("guest_testdir", "/tmp")
    filled = False
    number = 0

    try:
        error_context.context("Start filling the disk in %s" % fill_dir, test.log.info)
        cmd = params.get("fillup_cmd")
        while not filled:
            # As we want to test the backing file, so bypass the cache
            tmp_cmd = cmd % (fill_dir, number, fillup_size)
            test.log.debug(tmp_cmd)
            s, o = session.cmd_status_output(tmp_cmd, timeout=fillup_timeout)
            if "No space left on device" in o:
                test.log.debug("Successfully filled up the disk")
                filled = True
            elif s != 0:
                test.fail("Command dd failed to execute: %s" % o)
            number += 1
    finally:
        error_context.context("Cleaning the temporary files...", test.log.info)
        try:
            clean_cmd = params.get("clean_cmd") % fill_dir
            session2.cmd(clean_cmd, ignore_all_errors=True)
        finally:
            show_fillup_dir_cmd = params.get("show_fillup_dir_cmd") % fill_dir
            output = session2.cmd(show_fillup_dir_cmd, ignore_all_errors=True)
            test.log.debug("The fill_up dir shows:\n %s", output)
            if session:
                session.close()
            if session2:
                session2.close()
