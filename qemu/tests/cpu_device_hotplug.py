import re
import time

from virttest import cpu, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Runs vCPU hotplug tests based on CPU device:
    """

    def hotplug(vm, current_cpus, total_cpus, vcpu_threads):
        for vcpu in range(current_cpus, total_cpus):
            error_context.context("hot-pluging vCPU %s" % vcpu, test.log.info)
            vm.hotplug_vcpu(cpu_id=vcpu, plug_command=hotplug_cmd)
            time.sleep(0.1)
        time.sleep(5)

    def hotunplug(vm, current_cpus, total_cpus, vcpu_threads):
        for vcpu in range(current_cpus, total_cpus):
            error_context.context("hot-unpluging vCPU %s" % vcpu, test.log.info)
            vm.hotplug_vcpu(cpu_id=vcpu, plug_command=unplug_cmd, unplug="yes")
            time.sleep(0.1)
        # Need more time to unplug, so sleeping more than hotplug.
        time.sleep(10)

    def verify(vm, total_cpus):
        output = vm.monitor.send_args_cmd("info cpus")
        test.log.debug("Output of info CPUs:\n%s", output)

        cpu_regexp = re.compile(r"CPU #(\d+)")
        total_cpus_monitor = len(cpu_regexp.findall(output))
        if total_cpus_monitor != total_cpus:
            test.fail(
                "Monitor reports %s CPUs, when VM should have"
                " %s" % (total_cpus_monitor, total_cpus)
            )
        error_context.context(
            "hotplugging finished, let's wait a few sec and"
            " check CPUs quantity in guest.",
            test.log.info,
        )
        if not utils_misc.wait_for(
            lambda: cpu.check_if_vm_vcpu_match(total_cpus, vm),
            60 + total_cpus,
            first=10,
            step=5.0,
            text="retry later",
        ):
            test.fail("CPU quantity mismatch cmd after hotplug !")
        error_context.context(
            "rebooting the vm and check CPU quantity !", test.log.info
        )
        vm.reboot()
        if not cpu.check_if_vm_vcpu_match(total_cpus, vm):
            test.fail("CPU quantity mismatch cmd after hotplug and reboot !")

    error_context.context(
        "boot the vm, with '-smp X,maxcpus=Y' option," "thus allow hotplug vcpu",
        test.log.info,
    )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    vm.wait_for_login(timeout=timeout)

    n_cpus_add = int(params.get("n_cpus_add", 1))
    n_cpus_remove = int(params.get("n_cpus_remove", 1))
    maxcpus = int(params.get("maxcpus", 240))
    current_cpus = int(params.get("smp", 2))
    int(params.get("onoff_iterations", 20))
    hotplug_cmd = params.get("cpu_hotplug_cmd", "")
    unplug_cmd = params.get("cpu_hotunplug_cmd", "")
    int(params.get("vcpu_cores", 1))
    vcpu_threads = int(params.get("vcpu_threads", 1))
    cpu_model = params.get("cpu_model", "host")
    unplug = params.get("unplug", "no")
    total_cpus = current_cpus

    if unplug == "yes":
        n_cpus_add = n_cpus_remove

    hotplug_cmd = hotplug_cmd.replace("CPU_MODEL", cpu_model)

    if (n_cpus_add * vcpu_threads) + current_cpus > maxcpus:
        test.log.warning("CPU quantity more than maxcpus, set it to %s", maxcpus)
        total_cpus = maxcpus
    else:
        total_cpus = current_cpus + (n_cpus_add * vcpu_threads)

    test.log.info("current_cpus=%s, total_cpus=%s", current_cpus, total_cpus)
    error_context.context(
        "check if CPUs in guest matches qemu cmd " "before hot-plug", test.log.info
    )
    if not cpu.check_if_vm_vcpu_match(current_cpus, vm):
        test.error("CPU quantity mismatch cmd before hotplug !")
    hotplug(vm, current_cpus, total_cpus, vcpu_threads)
    verify(vm, total_cpus)

    if unplug == "yes":
        hotunplug(vm, current_cpus, total_cpus, vcpu_threads)

        total_cpus = total_cpus - (n_cpus_remove * vcpu_threads)
        if total_cpus <= 0:
            total_cpus = current_cpus
        verify(vm, total_cpus)
