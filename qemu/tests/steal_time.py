import re
import time

from avocado.utils import process
from virttest import error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Steal time test:
    1) Boot two guests and bind to one same cpu
    2) Run stress inside both guests
    3) Check steal time in top inside guests
    4) Check if two qemu processes have equal cpu usage
    5) Check steal time in /proc/stat in guest
    6) Repeat step 4) after 60s, compare the steal time changed in two guests

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """

    def get_stat_val():
        """
        Get steal time value in /proc/stat
        """
        stat_val = []
        for session in sessions:
            val = session.cmd_output(stat_cmd).split()[8]
            stat_val.append(int(val))
        return stat_val

    stress_args = params["stress_args"]
    stress_tests = []
    sessions = []
    vms = env.get_all_vms()

    error_context.context("Run stress in both guests", test.log.info)
    for vm in vms:
        session = vm.wait_for_login()
        sessions.append(session)
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
        stress_tests.append(stress_test)

    time.sleep(10)
    top_cmd = params["top_cmd"]
    stat_cmd = params["stat_cmd"]

    try:
        error_context.context("Check steal time in guests", test.log.info)
        for session in sessions:
            output = session.cmd_output(top_cmd)
            top_st = re.findall(r",\s*(\d+.?\d+)\s*st", output)[0]
            if abs(float(top_st) - 50) > 10:
                test.fail("Guest steal time is not around 50")

        error_context.context("Check two qemu process cpu usage", test.log.info)
        cmd = "top -n1 -b -p %s -p %s | grep qemu-kvm | awk '{print $9}'" % (
            vms[0].get_pid(),
            vms[1].get_pid(),
        )
        cpu_usage = process.getoutput(cmd, shell=True).split()
        test.log.info("QEMU cpu usage are %s", cpu_usage)
        cpu_usage = sorted([float(x) for x in cpu_usage])
        if sum(cpu_usage) < 80 or cpu_usage[0] < 40:
            test.fail("Two qemu process didn't get equal cpu usage")

        error_context.context("Check steal time in /proc/stat", test.log.info)
        stat_val_pre = get_stat_val()
        test.log.info("Steal time value in /proc/stat is %s", stat_val_pre)
        time.sleep(60)
        stat_val_post = get_stat_val()
        test.log.info("After 60s, steal time value in /proc/stat is %s", stat_val_post)

        delta = list(map(lambda x, y: y - x, stat_val_pre, stat_val_post))
        if abs(delta[0] - delta[1]) > sum(delta) / 2 * 0.1:
            test.fail("Guest steal time change in /proc/stat is not close")

    finally:
        for stress_test in stress_tests:
            stress_test.unload_stress()
