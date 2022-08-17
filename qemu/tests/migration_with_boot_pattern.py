import logging
import time

import aexpect

from avocado.utils import astring
from virttest.utils_misc import InterruptedThread
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    KVM migration test:
    1) Start VM
    2) Wait in background for the occurrence of the boot_pattern while
       migrating the VM in a loop
    3) Issue one more migration after the pattern is reached
    4) Optionally send a line to serial port (to proceed booting) followed
       by yet another migration
    5) Login to the machine

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def wait_for_boot_pattern(boot_pattern, vm):
        """
        Waits till last_line_matches and survives vm-migration
        """
        patterns = [boot_pattern]
        while True:
            try:
                if vm.serial_console.read_until_last_line_matches(patterns,
                                                                  timeout=1):
                    return True
            except aexpect.ExpectError:
                pass

    vm = env.get_vm(params["main_vm"])
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    boot_pattern_timeout = float(params.get("boot_pattern_timeout", 3600))
    boot_pattern = params["boot_pattern"]
    post_boot_pattern_cmd = (params.get("post_boot_pattern_cmd", b'')
                             .encode(astring.ENCODING)
                             .decode("unicode_escape"))
    login_timeout = int(params.get("login_timeout", 360))

    error_context.context("Start VM and wait for pattern while migrating",
                          logging.info)
    end = time.time() + boot_pattern_timeout
    vm.create()
    thread = InterruptedThread(wait_for_boot_pattern,
                               args=(boot_pattern, vm))
    thread.start()

    try:
        while thread.isAlive():
            assert time.time() < end, ("Boot pattern not found in %ss"
                                       % boot_pattern_timeout)
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay,
                       env=env)
    except Exception:
        # If something bad happened in the main thread, ignore exceptions
        # raised in the background thread
        thread.join(timeout=10, suppress_exception=True)
        raise

    bg_result = thread.join()
    assert bg_result is True, ("Background thread failed, check the log "
                               "for details (%s)" % bg_result)

    error_context.context("Additional migration after the pattern is found",
                          logging.info)
    vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay, env=env)
    if post_boot_pattern_cmd:
        vm.serial_console.sendline(post_boot_pattern_cmd)
        error_context.context("Second migration after the "
                              "post-boot-pattern-cmd",
                              logging.info)
        vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay, env=env)
    error_context.context("Logging into the machine", logging.info)
    session = vm.wait_for_login(timeout=login_timeout)
    session.close()
