import re
import time

from avocado.utils import process
from virttest import error_context, utils_test, utils_time


@error_context.context_aware
def run(test, params, env):
    """
    Check time offset after hotplug a vcpu.

    1) sync host time with ntpserver
    2) boot guest with '-rtc base=utc,clock=host,driftfix=slew'
    3) stop auto sync service in guest (rhel7 only)
    4) sync guest system time with ntpserver
    5) hotplug a vcpu by qmp command
    6) query guest time offset with ntpserver for several times

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    os_type = params["os_type"]
    ntp_cmd = params["ntp_cmd"]
    ntp_host_cmd = params.get("ntp_host_cmd", ntp_cmd)

    error_context.context("Sync host system time with ntpserver", test.log.info)
    process.system(ntp_host_cmd, shell=True)

    vm = env.get_vm(params["main_vm"])
    if params["os_type"] == "windows":
        utils_time.sync_timezone_win(vm)
    session = vm.wait_for_login()

    ntp_query_cmd = params.get("ntp_query_cmd", "")
    query_times = int(params.get("query_times", "4"))
    query_internal = float(params.get("query_internal", "600"))
    drift_threshold = float(params.get("drift_threshold", "3"))

    error_context.context("Sync time from guest to ntpserver", test.log.info)
    if os_type == "windows":
        w32time_conf_cmd = params["w32time_conf_cmd"]
        session.cmd(w32time_conf_cmd)
        utils_test.start_windows_service(session, "w32time")
    session.cmd(ntp_cmd)

    error_context.context("Hotplug a vcpu to guest", test.log.info)
    if int(params["smp"]) < int(params["vcpus_maxcpus"]):
        vm.hotplug_vcpu_device(params["vcpu_devices"])
        time.sleep(1)
    else:
        test.error(
            "Invalid operation, valid index range 0:%d, used range 0:%d"
            % (int(params["vcpus_maxcpus"]) - 1, int(params["smp"]) - 1)
        )

    error_context.context("Check time offset via ntp server", test.log.info)
    for query in range(query_times):
        output = session.cmd_output(ntp_query_cmd)
        try:
            offset = re.findall(r"([+-]*\d+\.\d+)[s sec]", output, re.M)[-1]
        except IndexError:
            test.error("Failed to get time offset")
        if float(offset) >= drift_threshold:
            test.fail(
                "Uacceptable offset '%s', " % offset
                + "threshold '%s'" % drift_threshold
            )
        time.sleep(query_internal)
    session.close()
