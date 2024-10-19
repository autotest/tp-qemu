import re
import time

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check guest offset in non-event way.

    1) sync host system time with ntp server
    2) boot guest with '-rtc base=utc,clock=host,driftfix=slew'
    3) get output of "qom-get" command
    4) read RTC time inside guest
    5) adjust RTC time forward 1 hour in guest
    6) verify output of "qom-get"

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_hwtime(session):
        """
        Get guest's hardware clock in epoch.

        :param session: VM session.
        """
        hwclock_time_command = params.get("hwclock_time_command", "hwclock -u")
        hwclock_time_filter_re = params.get(
            "hwclock_time_filter_re", r"(\d+-\d+-\d+ \d+:\d+:\d+).*"
        )
        hwclock_time_format = params.get("hwclock_time_format", "%Y-%m-%d %H:%M:%S")
        output = session.cmd_output_safe(hwclock_time_command)
        try:
            str_time = re.findall(hwclock_time_filter_re, output)[0]
            guest_time = time.mktime(time.strptime(str_time, hwclock_time_format))
        except Exception as err:
            test.log.debug(
                "(time_format, output): (%s, %s)", hwclock_time_format, output
            )
            raise err
        return guest_time

    ntp_cmd = params["ntp_cmd"]

    error_context.context("Sync host system time with ntpserver", test.log.info)
    process.system(ntp_cmd, shell=True)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    hwclock_forward_cmd = params["hwclock_forward_cmd"]
    time_forward = params["time_forward"]
    drift_threshold = params["drift_threshold"]

    error_context.context("Get output of qom_get", test.log.info)
    qom_st1 = vm.monitor.qom_get("/machine", "rtc-time")

    error_context.context("Get hardware time of guest", test.log.info)
    hwclock_st1 = get_hwtime(session)
    test.log.debug("hwclock: guest time=%ss", hwclock_st1)

    error_context.context("Adjust guest hardware time forward 1 hour", test.log.info)
    session.cmd(hwclock_forward_cmd, timeout=120)

    error_context.context("Verify output of qom-get", test.log.info)
    qom_st2 = vm.monitor.qom_get("/machine", "rtc-time")

    qom_gap = int(qom_st2["tm_hour"]) - int(qom_st1["tm_hour"])
    if (qom_gap < 1) or (qom_gap > 2):
        test.fail(
            "Unexpected offset in qom-get, "
            "qom-get result before change guest's RTC time: %s, "
            "qom-get result after change guest's RTC time: %s" % (qom_st1, qom_st2)
        )

    error_context.context("Verify guest hardware time", test.log.info)
    hwclock_st2 = get_hwtime(session)
    test.log.debug("hwclock: guest time=%ss", hwclock_st2)
    session.close()
    if (hwclock_st1 - hwclock_st2 - float(time_forward)) > float(drift_threshold):
        test.fail(
            "Unexpected hwclock drift, " "hwclock: current guest time=%ss" % hwclock_st2
        )
