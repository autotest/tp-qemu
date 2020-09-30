import logging

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug vCPU device during boot stage.

    1) Launch a guest without vCPU device.
    2) Hotplug vCPU devices during boot stage and check.
    3) Check if the number of CPUs changes after guest alive.
    4) Reboot guest to hotunplug. (optional)
    5) Hotunplug plugged vCPU devices during boot stage. (optional)
    6) Recheck the number of CPUs after guest alive. (optional)

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vcpu_devices = params.objects("vcpu_devices")
    unplug_during_boot = params.get_boolean("unplug_during_boot")
    boot_patterns = [r".*Started udev Wait for Complete Device Initialization.*"]
    reboot_patterns = [r".*[Rr]ebooting.*", r".*[Rr]estarting system.*",
                       r".*[Mm]achine restart.*"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    smp = vm.cpuinfo.smp
    maxcpus = vm.cpuinfo.maxcpus

    error_context.base_context("Hotplug vCPU devices during boot stage.",
                               logging.info)
    error_context.context("Verify guest is in the boot stage.", logging.info)
    vm.serial_console.read_until_any_line_matches(boot_patterns)

    error_context.context("Hotplug vCPU devices, waiting for guest alive.",
                          logging.info)
    for vcpu_device in vcpu_devices:
        vm.hotplug_vcpu_device(vcpu_device)
    vm.wait_for_login().close()

    error_context.context("Check number of CPU inside guest.", logging.info)
    current_guest_cpus = vm.get_cpu_count()
    if current_guest_cpus != maxcpus:
        test.fail("Actual number of guest CPUs(%s) is not equal to"
                  " expected(%s) after hotplug." % (current_guest_cpus,
                                                    maxcpus))
    logging.info("CPU quantity(%s) in guest is correct.", current_guest_cpus)

    if unplug_during_boot:
        # 1) vm.reboot() will return a new session, which is not what we want.
        # 2) Send reboot command directly because it will close the ssh client
        # so we can not get the command status.
        error_context.base_context("Reboot guest to boot stage, hotunplug the "
                                   "vCPU device.", logging.info)
        vm.wait_for_login().sendline(params["reboot_command"])

        error_context.context("Verify guest is in boot stage after reboot.",
                              logging.info)
        vm.serial_console.read_until_any_line_matches(reboot_patterns)
        vm.serial_console.read_until_any_line_matches(boot_patterns)

        error_context.context("Hotunplug vCPU devices, waiting for guest "
                              "alive.", logging.info)
        for vcpu_device in reversed(vcpu_devices):
            vm.hotunplug_vcpu_device(vcpu_device)
        vm.wait_for_login().close()

        error_context.context("Check number of CPU inside guest after unplug.",
                              logging.info)
        current_guest_cpus = vm.get_cpu_count()
        if current_guest_cpus != smp:
            test.fail("Actual number of guest CPUs(%s) is not equal to "
                      "expected(%s) after hotunplug." % (current_guest_cpus,
                                                         smp))
        logging.info("CPU quantity(%s) in guest is correct.",
                     current_guest_cpus)
