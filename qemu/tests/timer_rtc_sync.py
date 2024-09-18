import re
import time

from avocado.utils import process
from virttest import env_process, error_context, utils_test, utils_time


@error_context.context_aware
def run(test, params, env):
    """
    RTC synchronization in guest:

    1) Sync host time with chronyd
    2) Boot the guest
    3) Sync guest time with chronyd
    4) Check the time in guest
    5) Set RTC time in guest
    6) Check the time again after about 11 mins

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_hwtime(session):
        """
        Get guest's hardware clock.

        :param session: VM session.
        """
        hwclock_time_command = params.get("hwclock_time_command", "hwclock -u")
        hwclock_time_filter_re = params.get(
            "hwclock_time_filter_re", r"(\d+-\d+-\d+ \d+:\d+:\d+)"
        )
        hwclock_time_format = params.get("hwclock_time_format", "%Y-%m-%d %H:%M:%S")
        output = session.cmd_output_safe(hwclock_time_command)
        try:
            str_time = re.findall(hwclock_time_filter_re, output)[0]
            guest_time = time.mktime(time.strptime(str_time, hwclock_time_format))
        except Exception as err:
            test.log.debug(
                "(time_format, time_string): (%s, %s)", hwclock_time_format, str_time
            )
            raise err
        return guest_time

    def verify_timedrift(session, is_hardware=False):
        """
        Verify timedrift between host and guest.

        :param session: VM session.
        :param is_hardware: if need to verify guest's hardware time.
        """
        # Command to run to get the current time
        time_command = params["time_command"]
        # Filter which should match a string to be passed to time.strptime()
        time_filter_re = params["time_filter_re"]
        # Time format for time.strptime()
        time_format = params["time_format"]
        timerdevice_drift_threshold = float(
            params.get("timerdevice_drift_threshold", 3)
        )

        time_type = "system" if not is_hardware else "harware"
        error_context.context("Check the %s time on guest" % time_type, test.log.info)
        host_time, guest_time = utils_test.get_time(
            session, time_command, time_filter_re, time_format
        )
        if is_hardware:
            guest_time = get_hwtime(session)
        drift = abs(float(host_time) - float(guest_time))
        if drift > timerdevice_drift_threshold:
            test.fail(
                "The guest's %s time is different with"
                " host's system time. Host time: '%s', guest time:"
                " '%s'" % (time_type, host_time, guest_time)
            )

    error_context.context("sync host time with NTP server", test.log.info)
    clock_sync_command = params["clock_sync_command"]
    process.system(clock_sync_command, shell=True)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Sync guest timezone before test", test.log.info)
    timeout = int(params.get("login_timeout", 360))
    utils_time.sync_timezone_linux(vm, timeout)

    session = vm.wait_for_login(timeout=timeout)

    error_context.context("check timedrift between guest and host.", test.log.info)
    verify_timedrift(session)
    verify_timedrift(session, is_hardware=True)

    # avoiding the time is synced during boot stage
    time.sleep(60)
    hwclock_set_cmd = params["hwclock_set_cmd"]
    session.cmd(hwclock_set_cmd)
    error_context.context("Waiting for 11 mins.", test.log.info)
    time.sleep(660)

    error_context.context(
        "check timedrift between guest and host after " "changing RTC time.",
        test.log.info,
    )
    verify_timedrift(session)
    verify_timedrift(session, is_hardware=True)
