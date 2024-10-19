import re
import time

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check if guest hang/stall if host clock is set back

    1) sync host system time with ntp server
    2) boot guest with "-rtc base=utc, clock=host, driftfix=slew"
    3) set host system time back
    4) reboot guest and do some operation.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    clock_sync_command = params["clock_sync_command"]
    error_context.context("Sync host system time with ntpserver", test.log.info)
    process.system(clock_sync_command, shell=True)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_serial_login()

    seconds_to_back = params["seconds_to_back"]
    set_host_time_back_cmd = params["set_host_time_back_cmd"]
    time_difference = int(params["time_difference"])
    epoch_time_cmd = params["epoch_time_cmd"]
    tolerance = float(params["tolerance"])

    error_context.context("Check time difference between host and guest", test.log.info)
    guest_timestr_ = session.cmd_output(epoch_time_cmd, timeout=120)
    host_timestr_ = process.run(epoch_time_cmd, shell=True).stdout_text
    host_epoch_time_, guest_epoch_time_ = map(
        lambda x: re.findall(r"epoch:\s+(\d+)", x)[0], [host_timestr_, guest_timestr_]
    )
    real_difference_ = abs(int(host_epoch_time_) - int(guest_epoch_time_))
    if real_difference_ > tolerance:
        test.error(
            "Unexpected timedrift between host and guest, host time: %s,"
            "guest time: %s" % (host_epoch_time_, guest_epoch_time_)
        )

    error_context.context("Set host system time back %s s" % seconds_to_back)
    process.system_output(set_host_time_back_cmd)
    time.sleep(10)

    try:
        vm.reboot(serial=True)
        session = vm.wait_for_serial_login()

        error_context.context(
            "Check time difference between host and guest", test.log.info
        )
        try:
            guest_timestr = session.cmd_output(epoch_time_cmd, timeout=120)
            session.close()
        except Exception:
            test.error("Guest error after set host system time back")
        host_timestr = process.run(epoch_time_cmd, shell=True).stdout_text
        host_epoch_time, guest_epoch_time = map(
            lambda x: re.findall(r"epoch:\s+(\d+)", x)[0], [host_timestr, guest_timestr]
        )
        real_difference = abs(int(host_epoch_time) - int(guest_epoch_time))
        if abs(real_difference - time_difference) >= tolerance:
            test.fail(
                "Unexpected timedrift between host and guest, host time: %s,"
                "guest time: %s" % (host_epoch_time, guest_epoch_time)
            )
    finally:
        time.sleep(10)
        error_context.context(
            "Sync host system time with ntpserver finally", test.log.info
        )
        process.system(clock_sync_command, shell=True)
