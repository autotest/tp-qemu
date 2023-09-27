import re

from avocado.utils import cpu
from virttest import env_process
from virttest import error_context
from virttest.qemu_monitor import QMPCmdError
from avocado.utils import process


@error_context.context_aware
def run(test, params, env):
    """
    numa_prealloc_threads test
    1) Boot a guest with thread-context and cpu-affinity option
    2) Obtain the thread-id
    3) Check the affinity obtained from QEMU is correct
    4) With sandbox enabled, try to change the cpu-affinity
       and handle the error

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    test.log.info("Check host CPUs number")
    host_cpus = int(cpu.online_count())
    smp_fixed = params.get_numeric("smp_fixed")
    if host_cpus < smp_fixed:
        test.cancel("The host only has %d CPUs, it needs at least %d!" % (host_cpus, smp_fixed))

    params['not_preprocess'] = "no"
    timeout = params.get_numeric("login_timeout", 1000)
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=timeout)

    thread_context_device = vm.devices.get_by_params({"backend": "thread-context"})[0]
    thread_context_device_id = thread_context_device.get_param("id")
    error_msg = params.get("sandbox_error_message", "")

    thread_id = vm.monitor.qom_get(thread_context_device_id, "thread-id")
    if not thread_id:
        test.fail("No thread-id setted.")

    expected_cpu_affinity = thread_context_device.get_param("cpu-affinity")
    cpu_affinity = vm.monitor.qom_get(thread_context_device_id, "cpu-affinity")
    affinity = str(cpu_affinity[0]) + "-" + str(cpu_affinity[-1])
    test.log.debug("The affinity: %s and the expected_cpu_affinity: %s"
                   % (affinity, expected_cpu_affinity))
    if expected_cpu_affinity != affinity:
        test.fail("Test and QEMU cpu-affinity does not match!")

    cmd_taskset = "taskset -c -p " + str(thread_id)
    output = process.getoutput(cmd_taskset)
    if not re.search(affinity, output):
        test.fail("The affinities %s and %s do not match!"
                  % (affinity, str(output)))

    sandbox = params.get("qemu_sandbox", "on")
    if sandbox == "on":
        try:
            # The command is expected to fail
            vm.monitor.qom_set(thread_context_device_id, "cpu-affinity", cpu_affinity)
        except QMPCmdError as e:
            test.log.debug("The expected error message: %s and the output: %s"
                           % (error_msg, e.data))
            if not re.search(error_msg, str(e.data)):
                test.fail("Can not get expected error message: %s" % error_msg)
