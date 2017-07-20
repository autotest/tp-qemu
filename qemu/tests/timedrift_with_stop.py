import logging
import time
import os
import signal

from avocado.utils import process
from virttest import utils_test
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Time drift test with stop/continue the guest:

    1) Log into a guest.
    2) Take a time reading from the guest and host.
    3) Stop the running of the guest
    4) Sleep for a while
    5) Continue the guest running
    6) Take a second time reading.
    7) If the drift (in seconds) is higher than a user specified value, fail.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def get_hw_time():
        """
        Get the hardware clock
        """
        get_hw_time_cmd = params.get("get_hw_time_cmd",
                                     'TZ=UTC date +"%s" -d "`hwclock`"')
        host_hw_time = process.system_output(get_hw_time_cmd, shell=True)
        if not host_hw_time:
            test.fail("Cannot get the correct host hardware time")
        guest_hw_time = session.cmd(get_hw_time_cmd)
        if not guest_hw_time:
            test.fail("Cannot get the correct guest hardware time")
        return (host_hw_time, guest_hw_time)

    login_timeout = int(params.get("login_timeout", 360))
    sleep_time = int(params.get("sleep_time", 30))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    boot_option_added = params.get("boot_option_added")
    boot_option_removed = params.get("boot_option_removed")
    if boot_option_added or boot_option_removed:
        utils_test.update_boot_option(vm,
                                      args_removed=boot_option_removed,
                                      args_added=boot_option_added)

    session = vm.wait_for_login(timeout=login_timeout)

    # Collect test parameters:
    # Command to run to get the current time
    time_command = params["time_command"]
    # Filter which should match a string to be passed to time.strptime()
    time_filter_re = params["time_filter_re"]
    # Time format for time.strptime()
    time_format = params["time_format"]
    rtc_clock = params.get("rtc_clock", "host")
    drift_threshold = float(params.get("drift_threshold", "10"))
    drift_threshold_single = float(params.get("drift_threshold_single", "3"))
    stop_iterations = int(params.get("stop_iterations", 1))
    stop_time = int(params.get("stop_time", 60))
    stop_with_signal = params.get("stop_with_signal") == "yes"

    # Get guest's pid.
    pid = vm.get_pid()

    try:
        # Get initial time
        # (ht stands for host time, gt stands for guest time)
        (ht0, gt0) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)

        # Stop the guest
        for i in range(stop_iterations):
            # Get time before current iteration
            (ht0_, gt0_) = utils_test.get_time(session, time_command,
                                               time_filter_re, time_format)
            # Get hardware clock time befure current iteration
            if not stop_with_signal:
                if params.get("os_type") == "linux" and rtc_clock == "host":
                    (hhwt0_, ghwt0_) = get_hw_time()

            # Run current iteration
            logging.info("Stop %s second: iteration %d of %d...",
                         stop_time, (i + 1), stop_iterations)
            if stop_with_signal:
                logging.debug("Stop guest")
                os.kill(pid, signal.SIGSTOP)
                time.sleep(stop_time)
                logging.debug("Continue guest")
                os.kill(pid, signal.SIGCONT)
            else:
                vm.pause()
                time.sleep(stop_time)
                vm.resume()

            # Sleep for a while to wait the interrupt to be reinjected
            logging.info("Waiting for the interrupt to be reinjected ...")
            time.sleep(sleep_time)

            # Get time after current iteration
            (ht1_, gt1_) = utils_test.get_time(session, time_command,
                                               time_filter_re, time_format)
            # Report iteration results
            host_delta = ht1_ - ht0_
            guest_delta = gt1_ - gt0_
            drift = abs(host_delta - guest_delta)

            # Get hardware time after current iteration
            if not stop_with_signal:
                if params.get("os_type") == "linux" and rtc_clock == "host":
                    (hhwt1_, ghwt1_) = get_hw_time()
                    host_hw_delta = float(hhwt1_) - float(hhwt0_)
                    guest_hw_delta = float(ghwt1_) - float(ghwt0_)

            # kvm guests CLOCK_MONOTONIC not count when guest is paused,
            # so drift need to subtract stop_time.
            if not stop_with_signal:
                drift = abs(drift - stop_time)
                if params.get("os_type") == "windows" and rtc_clock == "host":
                    drift = abs(host_delta - guest_delta)
                if params.get("os_type") == "linux" and rtc_clock == "host":
                    error_context.context("Check the hardware time on guest and host")
                    drift_hw = abs(host_hw_delta - guest_hw_delta)
                    logging.info("Drift of hardware at iteration %d: %.2f seconds",
                                 (i + 1), drift_hw)
                    if drift_hw > drift_threshold_single:
                        test.fail("Hardware time drift too large at iteration %d:"
                                  "%.2f seconds" % (i + 1, drift_hw))
            else:
                if params.get("os_type") == "windows" and rtc_clock == "host":
                    drift = abs(drift - stop_time)

            logging.info("Host duration (iteration %d): %.2f",
                         (i + 1), host_delta)
            logging.info("Guest duration (iteration %d): %.2f",
                         (i + 1), guest_delta)
            logging.info("Drift at iteration %d: %.2f seconds",
                         (i + 1), drift)
            # Fail if necessary
            if drift > drift_threshold_single:
                test.fail("Time drift too large at iteration %d: "
                          "%.2f seconds" % (i + 1, drift))

        # Get final time
        (ht1, gt1) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)

    finally:
        if session:
            session.close()
        # remove flags add for this test.
        if boot_option_added or boot_option_removed:
            utils_test.update_boot_option(vm,
                                          args_removed=boot_option_added,
                                          args_added=boot_option_removed)

    # Report results
    host_delta = ht1 - ht0
    guest_delta = gt1 - gt0
    drift = abs(host_delta - guest_delta)
    # kvm guests CLOCK_MONOTONIC not count when guest is paused,
    # so drift need to subtract stop_time.
    if not stop_with_signal:
        drift = abs(drift - stop_time * stop_iterations)
        if params.get("os_type") == "windows" and rtc_clock == "host":
            drift = abs(host_delta - guest_delta)
    elif params.get("os_type") == "windows" and rtc_clock == "host":
        drift = abs(drift - stop_time * stop_iterations)
    logging.info("Host duration (%d stops): %.2f",
                 stop_iterations, host_delta)
    logging.info("Guest duration (%d stops): %.2f",
                 stop_iterations, guest_delta)
    logging.info("Drift after %d stops: %.2f seconds",
                 stop_iterations, drift)

    # Fail if necessary
    if drift > drift_threshold:
        test.fail("Time drift too large after %d stops: "
                  "%.2f seconds" % (stop_iterations, drift))
