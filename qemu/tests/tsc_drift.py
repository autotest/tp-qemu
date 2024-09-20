import os
import re
import time

from avocado.utils import cpu, process
from virttest import data_dir


def run(test, params, env):
    """
    Check the TSC(time stamp counter) frequency of guest and host whether match
    or not

    1) Test the vcpus' TSC of host by C the program
    2) Copy the C code to the guest, complie and run it to get the vcpus' TSC
       of guest
    3) Sleep sometimes and get the TSC of host and guest again
    4) Compute the TSC frequency of host and guest
    5) Compare the frequency deviation between host and guest with standard

    :param test: QEMU test object
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    drift_threshold = float(params.get("drift_threshold"))
    interval = float(params.get("interval"))
    cpu_chk_cmd = params.get("cpu_chk_cmd")
    tsc_cmd_guest = params.get("tsc_cmd_guest", "./a.out")
    tsc_cmd_host = params.get("tsc_cmd_host", "./a.out")
    tsc_freq_path = os.path.join(data_dir.get_deps_dir(), "timedrift/get_tsc.c")
    host_freq = 0

    def get_tsc(machine="host", i=0):
        tsc_cmd = tsc_cmd_guest
        if tsc_cmd == "host":
            tsc_cmd = tsc_cmd_host
        cmd = "taskset %s %s" % (1 << i, tsc_cmd)
        if machine == "host":
            result = process.run(cmd, ignore_status=True)
            s, o = result.exit_status, result.stdout
        else:
            s, o = session.cmd_status_output(cmd)
        if s != 0:
            test.error("Fail to get tsc of host, ncpu: %d" % i)
        o = re.findall(r"(\d+)", o)[0]
        return float(o)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    if not os.path.exists(tsc_cmd_guest):
        process.run("gcc %s" % tsc_freq_path)

    ncpu = cpu.online_count()

    test.log.info("Interval is %s", interval)
    test.log.info("Determine the TSC frequency in the host")
    for i in range(ncpu):
        tsc1 = get_tsc("host", i)
        time.sleep(interval)
        tsc2 = get_tsc("host", i)

        delta = tsc2 - tsc1
        test.log.info("Host TSC delta for cpu %s is %s", i, delta)
        if delta < 0:
            test.error("Host TSC for cpu %s warps %s" % (i, delta))

        host_freq += delta / ncpu
    test.log.info("Average frequency of host's cpus: %s", host_freq)

    if session.cmd_status("test -x %s" % tsc_cmd_guest):
        vm.copy_files_to(tsc_freq_path, "/tmp/get_tsc.c")
        if session.cmd_status("gcc /tmp/get_tsc.c") != 0:
            test.error("Fail to compile program on guest")

    s, guest_ncpu = session.cmd_status_output(cpu_chk_cmd)
    if s != 0:
        test.error("Fail to get cpu number of guest")

    success = True
    for i in range(int(guest_ncpu)):
        tsc1 = get_tsc("guest", i)
        time.sleep(interval)
        tsc2 = get_tsc("guest", i)

        delta = tsc2 - tsc1
        test.log.info("Guest TSC delta for vcpu %s is %s", i, delta)
        if delta < 0:
            test.log.error("Guest TSC for vcpu %s warps %s", i, delta)

        ratio = 100 * (delta - host_freq) / host_freq
        test.log.info("TSC drift ratio for vcpu %s is %s", i, ratio)
        if abs(ratio) > drift_threshold:
            test.log.error("TSC drift found for vcpu %s ratio %s", i, ratio)
            success = False

    if not success:
        test.fail("TSC drift found for the guest, please check the " "log for details")

    session.close()
