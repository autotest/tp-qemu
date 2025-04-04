import os.path
import tempfile
import time


def run(test, params, env):
    """
    VM save / restore test:

    1) Wait save_restore_start_delay seconds (default=10.0)
    2) Verify VM is running
    3) Pause, save VM to file (optionally in save_restore_path), verify paused.
    4) wait save_restore_delay seconds (if specified)
    5) restore VM from file, verify running
    6) Repeat save_restore_repeat times or
       until save_restore_duration seconds pass.

    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_save_filename(path="", file_pfx=""):
        """
        Generate a guaranteed not to clash filename.

        @oaram: path: Optional base path to place file
        :param file_pfxx: Optional prefix to filename
        :return: absolute path to new non-clashing filename
        """
        if not path:
            path = tempfile.gettempdir()
        fd, filename = tempfile.mkstemp(prefix=file_pfx, dir=path)
        os.close(fd)
        return filename

    def nuke_filename(filename):
        """
        Try to unlink filename, ignore any os errors.
        """
        try:
            os.unlink(filename)
        except OSError:
            pass

    def check_system(test, vm, timeout):
        """
        Raise TestFail if system is not in expected state
        """
        session = None
        try:
            try:
                session = vm.wait_for_login(timeout=timeout)
                result = session.is_responsive(timeout=timeout / 10.0)
                if not result:
                    test.log.warning("Login session established, but non-responsive")
                    # assume guest is just busy with stuff
            except:
                test.fail("VM check timed out and/or VM non-responsive")
        finally:
            del session

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=600)

    start_delay = float(params.get("save_restore_start_delay", "10.0"))
    restore_delay = float(params.get("save_restore_delay", "0.0"))
    save_restore_duration = float(params.get("save_restore_duration", "60.0"))
    repeat = int(params.get("save_restore_repeat", "1"))

    path = os.path.abspath(params.get("save_restore_path", "/tmp"))
    file_pfx = vm.name + "-"
    save_file = get_save_filename(path, file_pfx)

    save_restore_bg_command = params.get("save_restore_bg_command")
    bg_command_pid = None
    if save_restore_bg_command:
        session.cmd(save_restore_bg_command + " &")
        try:
            # assume sh-like shell, try to get background process's pid
            bg_command_pid = int(session.cmd("jobs -rp"))
        except ValueError:
            test.log.warning("Background guest command 'job -rp' output not PID")
    del session  # don't leave stray ssh session lying around over save/restore

    start_time = time.time()
    # 'now' needs outside scope for error.TestFail() at end
    # especially if exception thrown in loop before completion
    now = time_to_stop = start_time + save_restore_duration
    while True:
        try:
            vm.verify_kernel_crash()
            check_system(test, vm, 120)  # networking needs time to recover
            test.log.info(
                "Save/restores left: %d (or %0.4f more seconds)",
                repeat,
                (time_to_stop - time.time()),
            )
            if start_delay:
                test.log.debug("Sleeping %0.4f seconds start_delay", start_delay)
                time.sleep(start_delay)
            vm.pause()
            vm.verify_kernel_crash()
            save_file = get_save_filename(path, file_pfx)
            vm.save_to_file(save_file)
            vm.verify_kernel_crash()
            if restore_delay:
                test.log.debug("Sleeping %0.4f seconds restore_delay", restore_delay)
                time.sleep(restore_delay)
            vm.restore_from_file(save_file)
            vm.verify_kernel_crash()
            vm.resume()  # make sure some work gets done
            vm.verify_kernel_crash()
            now = time.time()
        finally:
            if save_file:
                nuke_filename(save_file)  # make sure these are cleaned up
        # Prepare/check next loop itteration
        repeat -= 1
        # TODO: or BG test status==foo
        if (now >= time_to_stop) or (repeat <= 0):
            break
        save_file = get_save_filename(path, file_pfx)
    # Check the final save/restore cycle
    check_system(test, vm, 120)  # networking needs time to recover
    test.log.info("Save/Restore itteration(s) complete.")
    if save_restore_bg_command and bg_command_pid:
        session = vm.wait_for_login(timeout=120)
        status = session.cmd_status("kill %d" % bg_command_pid)
        if status != 0:
            test.log.warning("Background guest command kill %d failed", bg_command_pid)
        del session
    if repeat > 0:  # time_to_stop reached but itterations didn't complete
        test.fail(
            "Save/Restore save_restore_duration"
            " exceeded by %0.4f seconds with %d itterations"
            " remaining." % (now - time_to_stop, repeat + 1)
        )
