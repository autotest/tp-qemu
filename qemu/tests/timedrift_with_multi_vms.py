import random
import re

from avocado.utils import cpu, process, service
from virttest import env_process, error_context, utils_time


@error_context.context_aware
def run(test, params, env):
    """
    Check the timedrift on all the guests when attached all guests to CPUs

    1) boot the multi guests, e.g., boot 4 vms
    2) pin every guest process to one physical CPU
    3) reboot one of the guests, or change the time of one guest
    4) check the timedrift on all the guests

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def verify_guest_clock_source(session, expected):
        """
        :param session: VM session
        :param expected: expected clocksource
        """
        if expected not in session.cmd(clocksource_cmd):
            test.fail("Guest doesn't use '%s' clocksource" % expected)

    ntp_cmd = params["ntp_cmd"]
    ntp_stop_cmd = params["ntp_stop_cmd"]
    ntp_query_cmd = params["ntp_query_cmd"]
    ntp_service = params["ntp_service"]
    clocksource = params.get("clocksource", "kvm-clock")
    clocksource_cmd = params["clocksource_cmd"]
    expected_time_drift = params["expected_time_drift"]
    same_cpu = params["same_cpu"]

    error_context.context("Sync host time with ntp server", test.log.info)
    service_manager = service.ServiceManager()
    service_manager.stop(ntp_service)
    process.system(ntp_cmd, shell=True)

    error_context.context("Boot four guests", test.log.info)
    params["start_vm"] = "yes"
    vms = params.get("vms").split()
    vm_obj = []
    sessions = []
    host_cpu_list = cpu.online_list()
    if same_cpu == "no":
        if len(host_cpu_list) < len(vms):
            test.cancel("There aren't enough physical cpus to pin all guests")
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        vm_obj.append(vm)
        sessions.append(vm.wait_for_login())

    error_context.context("Pin guest to physical cpu", test.log.info)
    for vmid, se in enumerate(sessions):
        # Get the respective vm object
        cpu_id = vmid if same_cpu == "no" else 0
        process.system(
            "taskset -cp %s %s" % (host_cpu_list[cpu_id], vm_obj[vmid].get_pid()),
            shell=True,
        )
        error_context.context("Check the current clocksource", test.log.info)
        currentsource = se.cmd_output_safe(clocksource_cmd)
        if clocksource not in currentsource:
            error_context.context(
                "Update guest kernel cli to %s" % clocksource, test.log.info
            )
            utils_time.update_clksrc(vm_obj[vmid], clksrc=clocksource)
            verify_guest_clock_source(se, clocksource)
        error_context.context("Stop ntp service in guest", test.log.info)
        status, output = se.cmd_status_output(ntp_stop_cmd)

    vmid_test = random.randint(0, len(vms) - 1)
    vm = vm_obj[vmid_test]
    se = sessions[vmid_test]
    if same_cpu == "no":
        error_context.context("Reboot one of the guests", test.log.info)
        se = vm.reboot(se)
        status, output = se.cmd_status_output(ntp_stop_cmd)
        sessions[vmid_test] = se
    else:
        error_context.context("Change time in one of the guests", test.log.info)
        change_time_cmd = params["change_time_cmd"]
        se.cmd_output_safe(change_time_cmd)

    error_context.context("Check the timedrift on all the guests", test.log.info)
    fail_offset = []
    for vmid, se in enumerate(sessions):
        if same_cpu == "yes" and vmid == vmid_test:
            continue
        output = se.cmd_output_safe(ntp_query_cmd)
        offset = float(re.findall(r"[+-]?(\d+\.\d+)", output, re.M)[-1])
        test.log.info("The time drift of guest %s is %ss.", vmid, offset)
        if offset > float(expected_time_drift):
            fail_offset.append((vmid, offset))
    if fail_offset:
        test.fail(
            "The time drift of following guests %s are larger than 5s." % fail_offset
        )
