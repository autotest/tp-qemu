from virttest import error_context

from provider import cpu_utils


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
    boot_patterns = [
        r".*Started udev Wait for Complete Device Initialization.*",
        r".*Finished .*Wait for udev To Complete Device Initialization.*",
    ]
    reboot_patterns = [
        r".*[Rr]ebooting.*",
        r".*[Rr]estarting system.*",
        r".*[Mm]achine restart.*",
    ]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.base_context("Hotplug vCPU devices during boot stage.", test.log.info)
    error_context.context("Verify guest is in the boot stage.", test.log.info)
    vm.serial_console.read_until_any_line_matches(boot_patterns)

    error_context.context(
        "Hotplug vCPU devices, waiting for guest alive.", test.log.info
    )
    for vcpu_device in vcpu_devices:
        vm.hotplug_vcpu_device(vcpu_device)
    vm.wait_for_login().close()

    error_context.context("Check number of CPU inside guest.", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.fail("Actual number of guest CPUs is not equal to expected")

    if unplug_during_boot:
        # 1) vm.reboot() will return a new session, which is not what we want.
        # 2) Send reboot command directly because it will close the ssh client
        # so we can not get the command status.
        error_context.base_context(
            "Reboot guest to boot stage, hotunplug the " "vCPU device.", test.log.info
        )
        vm.wait_for_login().sendline(params["reboot_command"])

        error_context.context(
            "Verify guest is in boot stage after reboot.", test.log.info
        )
        vm.serial_console.read_until_any_line_matches(reboot_patterns)
        vm.serial_console.read_until_any_line_matches(boot_patterns)

        error_context.context(
            "Hotunplug vCPU devices, waiting for guest " "alive.", test.log.info
        )
        for vcpu_device in reversed(vcpu_devices):
            vm.hotunplug_vcpu_device(vcpu_device)
        vm.wait_for_login().close()

        error_context.context(
            "Check number of CPU inside guest after unplug.", test.log.info
        )
        if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
            test.fail(
                "Actual number of guest CPUs is not equal to expected "
                "after hotunplug."
            )
