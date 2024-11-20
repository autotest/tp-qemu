from aexpect import ShellCmdError
from virttest import error_context, utils_misc
from virttest.virt_vm import VMDeviceCheckError

from provider import cpu_utils, win_wora


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug/hotunplug of vcpu device.

    1) Boot up guest w/o vcpu device.
    2) Hot plug/unplug vcpu devices and check successfully or not. (qemu side)
    3) Check if the number of CPUs in guest changes accordingly. (guest side)
    4) Do sub test after hot plug/unplug.
    5) Recheck the number of CPUs in guest.
    6) Check the CPU topology of guest. (if all vcpu plugged)

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def check_guest_cpu_count():
        if not utils_misc.wait_for(
            lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm),
            verify_wait_timeout,
            first=sleep_after_change,
        ):
            test.fail("Actual number of guest CPUs is not equal to expected")

    def sub_hotunplug():
        error_context.context(
            "Hotunplug vcpu devices after vcpu %s" % hotpluggable_test, test.log.info
        )
        for plugged_dev in pluggable_vcpu_dev[::-1]:
            try:
                vm.hotunplug_vcpu_device(plugged_dev)
            except VMDeviceCheckError:
                if not vm.is_paused():
                    raise
                test.log.warning(
                    "%s can not be unplugged directly because "
                    "guest is paused, will check again after "
                    "resume",
                    plugged_dev,
                )
                vm.params["vcpu_enable_%s" % plugged_dev] = "no"

    def sub_reboot():
        error_context.context(
            "Reboot guest after vcpu %s" % hotpluggable_test, test.log.info
        )
        vm.reboot(
            session=session, method=params["reboot_method"], timeout=login_timeout
        )

    def sub_shutdown():
        error_context.context(
            "Shutdown guest after vcpu %s" % hotpluggable_test, test.log.info
        )
        shutdown_method = params["shutdown_method"]
        if shutdown_method == "shell":
            session.sendline(params["shutdown_command"])
            error_context.context(
                "waiting VM to go down (guest shell cmd)", test.log.info
            )
        elif shutdown_method == "system_powerdown":
            vm.monitor.system_powerdown()
            error_context.context(
                "waiting VM to go down (qemu monitor cmd)", test.log.info
            )
        if not vm.wait_for_shutdown(360):
            test.fail("Guest refuses to go down after vcpu %s" % hotpluggable_test)

    def sub_migrate():
        sub_migrate_reboot = sub_reboot  # noqa: F841
        sub_migrate_hotunplug = sub_hotunplug  # noqa: F841

        error_context.context(
            "Migrate guest after vcpu %s" % hotpluggable_test, test.log.info
        )
        vm.migrate()
        vm.verify_alive()
        sub_test_after_migrate = params.objects("sub_test_after_migrate")
        while sub_test_after_migrate:
            check_guest_cpu_count()
            sub_test = sub_test_after_migrate.pop(0)
            error_context.context("%s after migration completed" % sub_test)
            eval("sub_migrate_%s" % sub_test)()

    def sub_online_offline():
        error_context.context(
            "Offline then online guest CPUs after vcpu %s" % hotpluggable_test,
            test.log.info,
        )
        cpu_ids = list(current_guest_cpu_ids - guest_cpu_ids)
        cpu_ids.sort()
        cmd = "echo %d > /sys/devices/system/cpu/cpu%d/online"
        try:
            for cpu_id in cpu_ids[::-1]:
                session.cmd(cmd % (0, cpu_id))
            if not cpu_utils.check_if_vm_vcpu_match(cpu_count_before_test, vm):
                test.fail("Actual number of guest CPUs is not equal to expected")
            for cpu_id in cpu_ids:
                session.cmd(cmd % (1, cpu_id))
        except ShellCmdError as err:
            test.log.error(str(err))
            test.error("Failed to change the CPU state on guest.")

    def sub_pause_resume():
        error_context.context(
            "Pause guest to hotunplug all vcpu devices", test.log.info
        )
        vm.pause()
        sub_hotunplug()
        error_context.context("Resume guest after hotunplug")
        vm.resume()

    login_timeout = params.get_numeric("login_timeout", 360)
    sleep_after_change = params.get_numeric("sleep_after_cpu_change", 30)
    os_type = params["os_type"]
    hotpluggable_test = params["hotpluggable_test"]
    verify_wait_timeout = params.get_numeric("verify_wait_timeout", 60)
    sub_test_type = params.get("sub_test_type")
    check_cpu_topology = params.get_boolean("check_cpu_topology", True)

    vm = env.get_vm(params["main_vm"])
    maxcpus = vm.cpuinfo.maxcpus
    if not params.objects("vcpu_devices"):
        vcpus_count = (
            vm.cpuinfo.threads if params["machine_type"].startswith("pseries") else 1
        )
        pluggable_cpus = vm.cpuinfo.maxcpus // vcpus_count // 2
        params["vcpu_devices"] = " ".join(
            ["vcpu%d" % (count + 1) for count in range(pluggable_cpus)]
        )
        vm.destroy()
        if len(params.objects("vcpu_devices")) < 2:
            test.cancel("Insufficient maxcpus for multi-CPU hotplug")
        params["paused_after_start_vm"] = "no"
        vm.create(params=params)

    if vm.is_paused():
        vm.resume()
    vcpu_devices = params.objects("vcpu_devices")
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    cpu_count_before_test = vm.get_cpu_count()
    guest_cpu_ids = cpu_utils.get_guest_cpu_ids(session, os_type)

    error_context.context("Check the number of guest CPUs after startup", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.error(
            "The number of guest CPUs is not equal to the qemu command "
            "line configuration"
        )

    if hotpluggable_test == "hotplug":
        pluggable_vcpu_dev = vcpu_devices
    else:
        pluggable_vcpu_dev = vcpu_devices[::-1]

    if params.get_boolean("workaround_need"):
        win_wora.modify_driver(params, session)

    if params.get("pause_vm_before_hotplug", "no") == "yes":
        error_context.context(
            "Pause guest before %s" % hotpluggable_test, test.log.info
        )
        vm.pause()

    error_context.context("%s all vcpu devices" % hotpluggable_test, test.log.info)
    for vcpu_dev in pluggable_vcpu_dev:
        getattr(vm, "%s_vcpu_device" % hotpluggable_test)(vcpu_dev)
    if vm.is_paused():
        error_context.context(
            "Resume guest after %s" % hotpluggable_test, test.log.info
        )
        vm.resume()

    check_guest_cpu_count()
    current_guest_cpu_ids = cpu_utils.get_guest_cpu_ids(session, os_type)

    if sub_test_type:
        eval("sub_%s" % sub_test_type)()
        # Close old session since guest maybe dead/reboot
        if session:
            session.close()

    if vm.is_alive():
        session = vm.wait_for_login(timeout=login_timeout)
        check_guest_cpu_count()
        if vm.get_cpu_count() == maxcpus and check_cpu_topology:
            if not cpu_utils.check_if_vm_vcpu_topology_match(
                session, os_type, vm.cpuinfo, test, vm.devices
            ):
                session.close()
                test.fail("CPU topology of guest is inconsistent with " "expectations.")
