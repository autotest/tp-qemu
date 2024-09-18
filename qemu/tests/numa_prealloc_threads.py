import re

from avocado.utils import cpu, process
from virttest import env_process, error_context
from virttest.qemu_monitor import QMPCmdError


def check_affinity(affinity, cmd_taskset, stage, test):
    """
    :param affinity: the cpu affinity
    :param cmd_taskset: the taskset command
    :param stage: the new or current affinity
    :param test: QEMU test object
    """
    output = process.getoutput(cmd_taskset)
    actual_affinity = re.search(
        "%s affinity list: (%s)" % (stage, affinity), output
    ).group(1)
    if actual_affinity != affinity:
        test.fail(
            "Expect %s cpu affinity '%s', but get '%s'"
            % (stage, affinity, actual_affinity)
        )


def convert_affinity(affinity):
    """
    convert the cpu affinitys between list (ex: [1, 2, 3])
    and qemu-kvm command line style (ex: 1-3)
    """
    if isinstance(affinity, str):
        start, end = affinity.split("-")
        output = list(range(int(start), int(end) + 1))
    elif isinstance(affinity, list):
        if len(affinity) == 1:
            output = str(affinity[0])
        else:
            output = "%s-%s" % (affinity[0], affinity[-1])
    else:
        raise TypeError(f"unexpected affinity type: {type(affinity).__name__}")
    return output


@error_context.context_aware
def run(test, params, env):
    """
    numa_prealloc_threads test
    1) Boot a guest with thread-context and cpu-affinity option
    2) Obtain the thread-id
    3) Check the affinity obtained from QEMU is correct
    4) With sandbox enabled, try to change the cpu-affinity
       and handle the error
    5) Set externally a new CPU affinity
    6) Check QEMU main thread remains untouched

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    error_context.base_context("Check host CPUs number", test.log.info)
    host_cpus = int(cpu.online_count())
    smp_fixed = params.get_numeric("smp_fixed")
    if host_cpus < smp_fixed:
        test.cancel(
            "The host only has %d CPUs, it needs at least %d!" % (host_cpus, smp_fixed)
        )

    params["not_preprocess"] = "no"
    first_cpu_affinity = params.get("first_cpu-affinity")
    second_cpu_affinity = params.get("second_cpu-affinity")
    operation_type = params.get("operation")
    timeout = params.get_numeric("login_timeout", 1000)
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=timeout)

    error_context.context("Obtain the thread ID", test.log.info)
    thread_context_device = vm.devices.get_by_params({"backend": "thread-context"})[0]
    thread_context_device_id = thread_context_device.get_param("id")
    error_msg = params.get("sandbox_error_message", "")

    thread_id = vm.monitor.qom_get(thread_context_device_id, "thread-id")
    if not thread_id:
        test.fail("No thread-id setted.")

    error_context.context("Check the CPU affinity", test.log.info)
    qemu_cpu_affinity = thread_context_device.get_param("cpu-affinity", "0")
    cpu_affinity = vm.monitor.qom_get(thread_context_device_id, "cpu-affinity")
    affinity = convert_affinity(cpu_affinity)
    test.log.debug(
        "The affinity: %s and the qemu_cpu_affinity: %s", affinity, qemu_cpu_affinity
    )
    if qemu_cpu_affinity != affinity:
        test.fail("Test and QEMU cpu-affinity does not match!")

    cmd_taskset = "taskset -c -p %s" % thread_id
    check_affinity(affinity, cmd_taskset, "current", test)

    sandbox = params.get("qemu_sandbox", "on")

    error_context.base_context(
        "Setting cpu-affinity: %s" % first_cpu_affinity, test.log.info
    )
    try:
        vm.monitor.qom_set(
            thread_context_device_id,
            "cpu-affinity",
            convert_affinity(first_cpu_affinity),
        )
    except QMPCmdError as e:
        if sandbox == "off":
            test.fail(
                "Set cpu-affinity '%s' failed as: %s"
                % (first_cpu_affinity, str(e.data))
            )
        if not re.search(error_msg, str(e.data)):
            test.fail("Cannot get expected error message: %s" % error_msg)
        test.log.debug("Get the expected error message: %s", error_msg)
    else:
        if sandbox == "on":
            test.fail("Set cpu-affinity should fail when sandbox=on")
        affinity = first_cpu_affinity
    check_affinity(affinity, cmd_taskset, "current", test)

    if operation_type != "boot_cpu_affinity":
        error_context.base_context("Set externally a new CPU affinity", test.log.info)
        cmd_taskset = "taskset -c -p %s %s" % (second_cpu_affinity, str(thread_id))
        error_context.context("Verify the new cpu-affinity", test.log.info)
        check_affinity(second_cpu_affinity, cmd_taskset, "new", test)

        error_context.context(
            "Checking QEMU main thread remains untouched", test.log.info
        )
        cmd_taskset = "taskset -c -p %s" % vm.get_pid()
        check_affinity(qemu_cpu_affinity, cmd_taskset, "current", test)
