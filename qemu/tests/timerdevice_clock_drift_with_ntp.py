import os

import aexpect
from avocado.utils import process
from virttest import data_dir, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Timer device check clock frequency offset using chrony on CPU starved guest:

    1) Check for an appropriate clocksource on host.
    2) Boot the guest.
    3) Copy time-warp-test.c to guest.
    4) Compile the time-warp-test.c.
    5) Stop chronyd and apply load on guest.
    6) Pin every vcpu to a physical cpu.
    7) Verify each vcpu is pinned on host.
    8) Run time-warp-test on guest.
    9) Start chronyd on guest.
    10) Check the drift in /var/lib/chrony/drift file on guest after hours
        of running.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def _drift_file_exist():
        try:
            session.cmd("test -f /var/lib/chrony/drift")
            return True
        except Exception:
            return False

    error_context.context("Check for an appropriate clocksource on host", test.log.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if "tsc" not in process.getoutput(host_cmd):
        test.cancel("Host must use 'tsc' clocksource")

    error_context.context("Boot the guest", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    sess_guest_load = vm.wait_for_login(timeout=timeout)

    error_context.context("Copy time-warp-test.c to guest", test.log.info)
    src_file_name = os.path.join(
        data_dir.get_deps_dir(), "tsc_sync", "time-warp-test.c"
    )
    vm.copy_files_to(src_file_name, "/tmp")

    error_context.context("Compile the time-warp-test.c", test.log.info)
    cmd = "cd /tmp/;"
    cmd += " yum install -y popt-devel;"
    cmd += " rm -f time-warp-test;"
    cmd += " gcc -Wall -o time-warp-test time-warp-test.c -lrt"
    sess_guest_load.cmd(cmd)

    error_context.context("Stop chronyd and apply load on guest", test.log.info)
    sess_guest_load.cmd("systemctl stop chronyd")
    load_cmd = "for ((I=0; I<`grep 'processor id' /proc/cpuinfo| wc -l`; I++));"
    load_cmd += " do taskset $(( 1 << $I )) /bin/bash -c 'for ((;;)); do X=1; done &';"
    load_cmd += " done"
    sess_guest_load.cmd(load_cmd)

    error_context.context("Pin every vcpu to a physical cpu", test.log.info)
    host_cpu_cnt_cmd = params["host_cpu_cnt_cmd"]
    host_cpu_num = process.system_output(host_cpu_cnt_cmd, shell=True).strip()
    host_cpu_list = (_ for _ in range(int(host_cpu_num)))
    cpu_pin_list = list(zip(vm.vcpu_threads, host_cpu_list))
    if len(cpu_pin_list) < len(vm.vcpu_threads):
        test.cancel("There isn't enough physical cpu to pin all the vcpus")
    for vcpu, pcpu in cpu_pin_list:
        process.system("taskset -p %s %s" % (1 << pcpu, vcpu))

    error_context.context("Verify each vcpu is pinned on host", test.log.info)

    error_context.context("Run time-warp-test", test.log.info)
    session = vm.wait_for_login(timeout=timeout)
    cmd = "/tmp/time-warp-test > /dev/null &"
    session.cmd(cmd)

    error_context.context("Start chronyd on guest", test.log.info)
    cmd = "systemctl start chronyd; sleep 1; echo"
    session.cmd(cmd)

    error_context.context("Check if the drift file exists on guest", test.log.info)
    test_run_timeout = float(params["test_run_timeout"])
    try:
        utils_misc.wait_for(_drift_file_exist, test_run_timeout, step=5)
    except aexpect.ShellCmdError as detail:
        test.error(
            "Failed to wait for the creation of"
            " /var/lib/chronyd/drift file. Detail: '%s'" % detail
        )

    error_context.context("Verify the drift file content on guest", test.log.info)
    output = session.cmd("cat /var/lib/chrony/drift").strip().split()[0]
    if int(abs(float(output))) > 30:
        test.fail("Failed to check the chrony drift. Output: '%s'" % output)
