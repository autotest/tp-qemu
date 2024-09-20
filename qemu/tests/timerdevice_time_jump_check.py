import time

from avocado.utils import cpu, process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    check time jumps in guest (only for Linux guest):

    1) boot guest with '-rtc base=utc,clock=host,driftfix=slew'
    2) check current clocksource in guest
    3) pin all vcpus to specfic host CPUs
    4) verify time jump

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    error_context.context(
        "Check the clock source currently used on guest", test.log.info
    )
    cmd = "cat /sys/devices/system/clocksource/"
    cmd += "clocksource0/current_clocksource"
    test.log.info("%s is current clocksource.", session.cmd_output(cmd))

    error_context.context("Pin every vcpu to physical cpu", test.log.info)
    host_cpu_num = cpu.total_count()
    host_cpu_list = (_ for _ in range(int(host_cpu_num)))
    if len(vm.vcpu_threads) > int(host_cpu_num):
        host_cpu_list = []
        for _ in range(len(vm.vcpu_threads)):
            host_cpu_list.append(_ % int(host_cpu_num))
    cpu_pin_list = list(zip(vm.vcpu_threads, host_cpu_list))

    for vcpu, pcpu in cpu_pin_list:
        process.system("taskset -p -c %s %s" % (pcpu, vcpu))

    check_cmd = params["check_cmd"]
    output = str(session.cmd_output(check_cmd)).splitlines()
    session.close()
    time_pattern = "%y-%m-%d %H:%M:%S"
    time_list = []
    for str_time in output:
        time_struct = time.strptime(str_time, time_pattern)
        etime = time.mktime(time_struct)
        time_list.append(etime)
    for idx, _ in enumerate(time_list):
        if idx < len(time_list) - 1:
            if _ == time_list[idx + 1] or (_ + 1) == time_list[idx + 1]:
                continue
            else:
                test.fail("Test fail, time jumps backward or forward on guest")
        else:
            break
