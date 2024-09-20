import re
import time

from virttest import error_context

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test if cpu hotplug cause guest time jump

    1) Launch a guest and let guest run some time
    2) Hotplug vCPU devices to guest and check guest cpu number
    3) Check if there is time jump in guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    wait_time = params.get_numeric("wait_time")
    error_context.context("Let guest run %s" % wait_time, test.log.info)
    time.sleep(wait_time)

    error_context.context("Hotplug vCPU devices", test.log.info)
    vcpu_devices = params.objects("vcpu_devices")
    for vcpu_device in vcpu_devices:
        vm.hotplug_vcpu_device(vcpu_device)

    error_context.context("Check number of CPU inside guest.", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.fail("Actual number of guest CPUs is not equal to expected")

    error_context.context("Check if guest has time jump", test.log.info)
    output = session.cmd_output("dmesg")
    session.close()
    time1 = float(
        re.findall(r"^\[\s*(\d+\.?\d+)\].*CPU.*has been hot-added$", output, re.M)[0]
    )
    time2 = float(
        re.findall(
            r"^\[\s*(\d+\.?\d+)\].*Will online and init " "hotplugged CPU", output, re.M
        )[0]
    )
    time_gap = time2 - time1
    test.log.info("The time gap is %.6fs", time_gap)
    expected_gap = params.get_numeric("expected_gap", target_type=float)
    if time_gap > expected_gap:
        test.fail("The time gap is more than expected")
