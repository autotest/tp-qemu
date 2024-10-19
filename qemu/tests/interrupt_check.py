import time

from virttest import error_context, utils_disk, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Check number of interrupt after do some test.
    1) Launch a guest
    2) Check number of interrupts with specified pattern
    3) Do sub test on guest
    4) Recheck number of interrupts

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def get_irq_info():
        """
        Get interrupt information using specified pattern
        """
        return session.cmd_output(
            "grep '%s' /proc/interrupts" % irq_pattern, print_func=test.log.info
        ).split()

    def analyze_interrupts(irq_before_test, irq_after_test):
        """
        Compare interrupt information and analyze them
        """
        error_context.context("Analyzing interrupts", test.log.info)
        filtered_result = [
            x for x in zip(irq_before_test, irq_after_test) if x[0] != x[1]
        ]
        if not filtered_result:
            test.fail(
                "Number of interrupts on the CPUs have not changed after"
                " test execution"
            )
        elif any([int(x[1]) < int(x[0]) for x in filtered_result]):
            test.fail("The number of interrupts has decreased")

    def dd_test():
        """
        dd test to increase the number of interrupts
        """
        vm_disks = utils_disk.get_linux_disks(session)
        extra_disk = list(vm_disks.keys())[0] if vm_disks else None
        if not extra_disk:
            test.error("No additional disks found")

        error_context.context("Execute dd write test", test.log.info)
        session.cmd(params["dd_write"] % extra_disk, timeout=120)
        irq_info_after_dd_write = get_irq_info()
        analyze_interrupts(irq_info_before_test, irq_info_after_dd_write)

        error_context.context("Execute dd read test", test.log.info)
        session.cmd(params["dd_read"] % extra_disk)
        irq_info_after_dd_read = get_irq_info()
        analyze_interrupts(irq_info_after_dd_write, irq_info_after_dd_read)

    def ping_test():
        """
        ping test to increase the number of interrupts
        """
        error_context.context("Execute ping test", test.log.info)
        utils_net.ping(guest_ip, 10, session=session)
        irq_info_after_ping = get_irq_info()
        analyze_interrupts(irq_info_before_test, irq_info_after_ping)

    def hotplug_test():
        """
        hotplug test to increase the number of interrupts
        """
        current_cpu = vm.get_cpu_count()
        vcpu_devices = params.objects("vcpu_devices")
        error_context.context("Execute hotplug CPU test", test.log.info)
        for vcpu_device in vcpu_devices:
            vm.hotplug_vcpu_device(vcpu_device)
        if not utils_misc.wait_for(
            lambda: vm.get_cpu_count() == current_cpu + len(vcpu_devices), 30
        ):
            test.fail("Actual number of guest CPUs is not equal to expected")
        guest_cpus = vm.get_cpu_count()
        irq_info_after_hotplug = get_irq_info()
        if len(irq_info_after_hotplug) != (
            len(irq_info_before_test) + len(vcpu_devices)
        ):
            test.fail("Number of CPUs for %s is incorrect" % irq_pattern)

        irq_num_before_hotplug = irq_info_before_test[1 : (current_cpu + 1)]
        irq_num_after_hotplug = irq_info_after_hotplug[1 : (guest_cpus + 1)]
        if sum(map(int, irq_num_after_hotplug)) <= sum(
            map(int, irq_num_before_hotplug)
        ):
            test.fail("Abnormal number of interrupts")

    def standby_test():
        """
        Guest standby and then check number of interrupts again
        """
        time.sleep(params.get_numeric("standby_time"))
        irq_info_after_standby = get_irq_info()
        analyze_interrupts(irq_info_before_test, irq_info_after_standby)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    guest_ip = vm.get_address()
    guest_ifname = utils_net.get_linux_ifname(session, vm.get_mac_address(0))
    irq_pattern = params["irq_pattern"].format(ifname=guest_ifname)
    test_execution = {
        "dd": dd_test,
        "ping": ping_test,
        "hotplug": hotplug_test,
        "standby": standby_test,
    }

    error_context.base_context(
        "Get interrupt info before executing test", test.log.info
    )
    irq_info_before_test = get_irq_info()

    error_context.context("Execute test to verify increased interrupts")
    try:
        test_execution[params["increase_test"]]()
        test.log.info("The number of interrupts increased correctly")
    finally:
        session.close()
        vm.destroy()
