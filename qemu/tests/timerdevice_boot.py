import logging
import time
import re

from avocado.utils import process
from virttest import utils_test
from virttest import utils_time
from virttest import funcatexit
from virttest import error_context


def _system(*args, **kwargs):
    kwargs["shell"] = True
    return process.system(*args, **kwargs)


@error_context.context_aware
def run(test, params, env):
    """
    Timer device boot guest:

    1) Stop chronyd and sync host clock's time with ntp server
    2) Add some load on host (Optional)
    3) Boot the guest with specific clock source
    4) Check the clock source currently used on guest
    5) Do some file operation on guest (Optional)
    6) Check the system time on guest and host (Optional)
    7) Check the hardware time on guest (linux only)
    8) Sleep period of time before reboot (Optional)
    9) Reboot guest (Optional)
    10) Check the system time on guest and host (Optional)
    11) Check the hardware time on guest (Optional)
    12) Restore guest's clock source

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_hwtime(session):
        """
        Get guest's hardware clock.

        :param session: VM session.
        """
        hwclock_time_command = params.get("hwclock_time_command",
                                          "hwclock -u")
        hwclock_time_filter_re = params.get("hwclock_time_filter_re",
                                            r"(\d+-\d+-\d+ \d+:\d+:\d+)")
        hwclock_time_format = params.get("hwclock_time_format",
                                         "%Y-%m-%d %H:%M:%S")
        output = session.cmd_output_safe(hwclock_time_command)
        try:
            str_time = re.findall(hwclock_time_filter_re, output)[0]
            guest_time = time.mktime(time.strptime(str_time, hwclock_time_format))
        except Exception as err:
            logging.debug(
                "(time_format, time_string): (%s, %s)", hwclock_time_format, str_time)
            raise err
        return guest_time

    def verify_timedrift(session, is_hardware=False, base_time=None):
        """
        Verify timedrift between two targets. ex. host and guest.

        :param session: VM session.
        :param is_hardware: if need to verify guest's hardware time.
        :param base_time: base time in qemu command, ex. "2006-06-17"
        """
        # Command to run to get the current time
        time_command = params["time_command"]
        # Filter which should match a string to be passed to time.strptime()
        time_filter_re = params["time_filter_re"]
        # Time format for time.strptime()
        time_format = params["time_format"]
        timerdevice_drift_threshold = float(params.get(
            "timerdevice_drift_threshold", 3))

        time_type = "system" if not is_hardware else "hardware"
        error_context.context("Check the %s time on guest" % time_type,
                              logging.info)
        host_time, guest_time = utils_test.get_time(session, time_command,
                                                    time_filter_re,
                                                    time_format)
        if is_hardware:
            guest_time = get_hwtime(session)
        if not base_time:
            drift = abs(float(host_time) - float(guest_time))
            if drift > timerdevice_drift_threshold:
                test.fail("The guest's %s time is different with"
                          " host's system time. Host time: '%s', guest time:"
                          " '%s'" % (time_type, host_time, guest_time))
        else:
            base_pattern = "%Y-%m-%dT%H:%M:%S"
            try:
                time_struct = time.strptime(base_time, base_pattern)
            except ValueError:
                logging.info("Add default time to base date: %s" % base_time)
                if params["os_type"] == "windows":
                    base_time += "T00:00:00"
                else:
                    base_time += "T08:00:00"
                try:
                    time_struct = time.strptime(base_time, base_pattern)
                except:
                    raise
            target_time = time.mktime(time_struct)
            # assume boot time will not large than 3 minutes
            if (guest_time - target_time) > 180:
                test.fail("The guest system time is not from base time "
                          "%s" % base_time)

    def get_current_clksrc(session):
        cmd = "cat /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        current_clksrc = session.cmd_output_safe(cmd)
        if "kvm-clock" in current_clksrc:
            return "kvm-clock"
        elif "tsc" in current_clksrc:
            return "tsc"
        elif "timebase" in current_clksrc:
            return "timebase"
        elif "acpi_pm" in current_clksrc:
            return "acpi_pm"
        return current_clksrc

    def update_clksrc(session, clksrc):
        """
        Update guest's clocksource, this func can work when not login
        into guest with ssh.

        :param session: VM session.
        :param clksrc: expected guest's clocksource.
        """
        avail_cmd = "cat /sys/devices/system/clocksource/clocksource0/"
        avail_cmd += "available_clocksource"
        avail_clksrc = session.cmd_output_safe(avail_cmd)
        if clksrc in avail_clksrc:
            clksrc_cmd = "echo %s > /sys/devices/system/clocksource/" % clksrc
            clksrc_cmd += "clocksource0/current_clocksource"
            status, output = session.cmd_status_output(clksrc_cmd)
            if status:
                test.fail("fail to update guest's clocksource to %s,"
                          "details: %s" % clksrc, output)
        else:
            test.error("please check the clocksource you want to set, "
                       "it's not supported by current guest, current "
                       "available clocksources: %s" % avail_clksrc)
    base_time = params.get("rtc_base")

    error_context.context("sync host time with NTP server",
                          logging.info)
    clock_sync_command = params["clock_sync_command"]
    process.system(clock_sync_command, shell=True)

    timerdevice_host_load_cmd = params.get("timerdevice_host_load_cmd")
    if timerdevice_host_load_cmd:
        error_context.context("Add some load on host", logging.info)
        process.system(timerdevice_host_load_cmd, shell=True,
                       ignore_bg_processes=True)
        host_load_stop_cmd = params.get("timerdevice_host_load_stop_cmd",
                                        "pkill -f 'do X=1'")
        funcatexit.register(env, params["type"], _system,
                            host_load_stop_cmd)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Sync guest timezone before test", logging.info)
    if params["os_type"] == 'linux':
        utils_time.sync_timezone_linux(vm)
    else:
        utils_time.sync_timezone_win(vm)

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_serial_login(timeout=timeout)

    timerdevice_clksource = params.get("timerdevice_clksource")
    need_restore_clksrc = False
    if timerdevice_clksource:
        origin_clksrc = get_current_clksrc(session)
        logging.info("guest is booted with %s" % origin_clksrc)

        if timerdevice_clksource != origin_clksrc:
            update_clksrc(session, timerdevice_clksource)
            need_restore_clksrc = True

    error_context.context("check timedrift between guest and host.",
                          logging.info)
    if base_time in ("utc", "localtime"):
        base_time = None
    verify_timedrift(session, base_time=base_time)
    if params["os_type"] == "linux":
        verify_timedrift(session, is_hardware=True, base_time=base_time)

    if params.get("timerdevice_reboot_test") == "yes":
        sleep_time = params.get("timerdevice_sleep_time")
        if sleep_time:
            error_context.context("Sleep '%s' secs before reboot" % sleep_time,
                                  logging.info)
            sleep_time = int(sleep_time)
            time.sleep(sleep_time)

        error_context.context("Check timedrift between guest and host "
                              "after reboot.", logging.info)
        vm.reboot(timeout=timeout, serial=True)
        verify_timedrift(session, base_time=base_time)
        if params["os_type"] == "linux":
            verify_timedrift(session, is_hardware=True, base_time=base_time)
    if need_restore_clksrc:
        update_clksrc(session, origin_clksrc)
    session.close()
