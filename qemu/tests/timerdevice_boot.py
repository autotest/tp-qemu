import re
import time

from avocado.utils import process
from virttest import env_process, error_context, funcatexit, utils_test, utils_time


def _system(*args, **kwargs):
    kwargs["shell"] = True
    return process.system(*args, **kwargs)


@error_context.context_aware
def run(test, params, env):
    """
    Timer device boot guest:

    1) Check host clock's sync status with chronyd
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
            status, output = session.cmd_status_output(clksrc_cmd, safe=True)
            if status:
                test.fail(
                    "fail to update guest's clocksource to %s," "details: %s" % clksrc,
                    output,
                )
        else:
            test.error(
                "please check the clocksource you want to set, "
                "it's not supported by current guest, current "
                "available clocksources: %s" % avail_clksrc
            )

    error_context.context("sync host time with NTP server", test.log.info)
    clock_sync_command = params["clock_sync_command"]
    process.system(clock_sync_command, shell=True)

    timerdevice_host_load_cmd = params.get("timerdevice_host_load_cmd")
    if timerdevice_host_load_cmd:
        error_context.context("Add some load on host", test.log.info)
        host_cpu_cnt_cmd = params["host_cpu_cnt_cmd"]
        host_cpu_cnt = int(process.system_output(host_cpu_cnt_cmd, shell=True).strip())
        timerdevice_host_load_cmd = timerdevice_host_load_cmd % int(host_cpu_cnt / 2)
        if params["os_type"] == "linux":
            process.system(
                timerdevice_host_load_cmd, shell=True, ignore_bg_processes=True
            )
        else:
            stress_bg = utils_test.HostStress(
                "stress", params, stress_args=timerdevice_host_load_cmd
            )
            stress_bg.load_stress_tool()
        host_load_stop_cmd = params.get(
            "timerdevice_host_load_stop_cmd", "pkill -f 'do X=1'"
        )
        funcatexit.register(env, params["type"], _system, host_load_stop_cmd)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Sync guest timezone before test", test.log.info)
    timeout = int(params.get("login_timeout", 360))
    if params["os_type"] == "linux":
        utils_time.sync_timezone_linux(vm, timeout)
    else:
        utils_time.sync_timezone_win(vm, timeout)

    session = vm.wait_for_serial_login(timeout=timeout)

    timerdevice_clksource = params.get("timerdevice_clksource")
    need_restore_clksrc = False
    if timerdevice_clksource:
        origin_clksrc = get_current_clksrc(session)
        test.log.info("guest is booted with %s", origin_clksrc)

        if timerdevice_clksource != origin_clksrc:
            update_clksrc(session, timerdevice_clksource)
            need_restore_clksrc = True

    error_context.context("check timedrift between guest and host.", test.log.info)
    verify_timedrift(session)
    if params["os_type"] == "linux":
        verify_timedrift(session, is_hardware=True)

    repeat_nums = params.get_numeric("repeat_nums")
    if repeat_nums:
        sleep_time = params["sleep_time"]
        for index in range(repeat_nums):
            time.sleep(int(sleep_time))
            verify_timedrift(session)
            if params["os_type"] == "linux":
                verify_timedrift(session, is_hardware=True)

    if params.get("timerdevice_reboot_test") == "yes":
        sleep_time = params.get("timerdevice_sleep_time")
        if sleep_time:
            error_context.context(
                "Sleep '%s' secs before reboot" % sleep_time, test.log.info
            )
            sleep_time = int(sleep_time)
            time.sleep(sleep_time)

        error_context.context(
            "Check timedrift between guest and host " "after reboot.", test.log.info
        )
        vm.reboot(timeout=timeout, serial=True)
        verify_timedrift(session)
        if params["os_type"] == "linux":
            verify_timedrift(session, is_hardware=True)
    if need_restore_clksrc:
        update_clksrc(session, origin_clksrc)
    session.close()
