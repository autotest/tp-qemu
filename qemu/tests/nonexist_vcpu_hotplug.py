import logging

from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    NOTE: hotplug_vcpu is added since RHEL.6.3,
          so not boot with hmp is consider here.
    Test steps:
        1) boot the vm with -smp X,maxcpus=Y
        2) after logged into the vm, check vcpus number
        3) hotplug non-existed(no in 1..160) vcpus to guest.
        4) check guest vcpu quantity, should didn't changed
    params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    hotplug_cmd = "cpu_set %s online"

    error_context.context("boot the vm, with '-smp X,maxcpus=Y' option,"
                          "thus allow hotplug vcpu", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("check if CPUs in guest matches qemu cmd "
                          "before hot-plug", logging.info)
    smp_by_cmd = int(params.get("smp"))
    if not utils_misc.check_if_vm_vcpu_match(smp_by_cmd, vm):
        test.error("CPU quantity mismatch cmd before hotplug !")
    # Start vCPU hotplug
    error_context.context("hotplugging non-existed vCPU...", logging.info)
    vcpus_need_hotplug = params.get("nonexist_vcpu", "-1 161").split(" ")
    for vcpu in vcpus_need_hotplug:
        try:
            error_context.context("hot-pluging vCPU %s" % vcpu, logging.info)
            output = vm.monitor.send_args_cmd(hotplug_cmd % vcpu)
        finally:
            error_context.context("output from monitor is: %s" % output,
                                  logging.info)
    # Windows is a little bit lazy that needs more secs to recognize.
    error_context.context("hotplugging finished, let's wait a few sec and"
                          " check cpus quantity in guest.", logging.info)
    if not utils_misc.wait_for(lambda: utils_misc.check_if_vm_vcpu_match(
                               smp_by_cmd, vm),
                               60, first=10, step=5.0, text="retry later"):
        test.fail("CPU quantity mismatch cmd after hotplug !")
