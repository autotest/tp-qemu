import random
import re
import time

from virttest import arch, error_context, utils_misc, utils_package
from virttest.utils_test import BackgroundTest

from provider import cpu_utils, win_wora


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug vcpu devices and execute stress test.

    1) Boot up guest without vcpu device.
    2) Hotplug vcpu devices and check successfully or not. (qemu side)
    3) Check if the number of CPUs in guest changes accordingly. (guest side)
    4) Execute stress test on all hotplugged vcpu devices
    5) Hotunplug vcpu devices during stress test
    6) Recheck the number of CPUs in guest.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def heavyload_install():
        if session.cmd_status(test_installed_cmd) != 0:  # pylint: disable=E0606
            test.log.warning(
                "Could not find installed heavyload in guest, will"
                " install it via winutils.iso "
            )
            winutil_drive = utils_misc.get_winutils_vol(session)
            if not winutil_drive:
                test.cancel("WIN_UTILS CDROM not found.")
            install_cmd = params["install_cmd"] % winutil_drive
            session.cmd(install_cmd)

    os_type = params["os_type"]
    vm_arch_name = params.get("vm_arch_name", arch.ARCH)
    login_timeout = params.get_numeric("login_timeout", 360)
    stress_duration = params.get_numeric("stress_duration", 180)
    verify_wait_timeout = params.get_numeric("verify_wait_timeout", 60)

    vm = env.get_vm(params["main_vm"])
    if not params.objects("vcpu_devices"):
        vcpus_count = (
            vm.cpuinfo.threads if params["machine_type"].startswith("pseries") else 1
        )
        pluggable_cpus = vm.cpuinfo.maxcpus // vcpus_count // 2
        vcpu_devices = ["vcpu%d" % (count + 1) for count in range(pluggable_cpus)]
        params["vcpu_devices"] = " ".join(vcpu_devices)
        vm.destroy()
        if len(vcpu_devices) < 2:
            test.cancel("Insufficient maxcpus for multi-CPU hotplug")
        params["paused_after_start_vm"] = "no"
        vm.create(params=params)

    if vm.is_paused():
        vm.resume()
    vcpu_devices = params.objects("vcpu_devices")
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    if params.get_boolean("workaround_need"):
        win_wora.modify_driver(params, session)

    error_context.context("Check the number of guest CPUs after startup", test.log.info)
    if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
        test.error(
            "The number of guest CPUs is not equal to the qemu command "
            "line configuration"
        )

    guest_cpu_ids = cpu_utils.get_guest_cpu_ids(session, os_type)
    for vcpu_dev in vcpu_devices:
        error_context.context("Hotplug vcpu device: %s" % vcpu_dev, test.log.info)
        vm.hotplug_vcpu_device(vcpu_dev)
    if not utils_misc.wait_for(
        lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm), verify_wait_timeout
    ):
        test.fail("Actual number of guest CPUs is not equal to expected")

    if os_type == "linux":
        stress_args = params["stress_args"]
        stress_tool = cpu_utils.VMStressBinding(vm, params, stress_args=stress_args)
        current_guest_cpu_ids = cpu_utils.get_guest_cpu_ids(session, os_type)
        plugged_cpu_ids = list(current_guest_cpu_ids - guest_cpu_ids)
        plugged_cpu_ids.sort()
        for cpu_id in plugged_cpu_ids:
            error_context.context(
                "Run stress on vCPU(%d) inside guest." % cpu_id, test.log.info
            )
            stress_tool.load_stress_tool(cpu_id)
        error_context.context(
            "Successfully launched stress sessions, execute "
            "stress test for %d seconds" % stress_duration,
            test.log.info,
        )
        time.sleep(stress_duration)
        if utils_package.package_install("sysstat", session):
            error_context.context("Check usage of guest CPUs", test.log.info)
            mpstat_cmd = "mpstat 1 5 -P %s | cat" % ",".join(map(str, plugged_cpu_ids))
            mpstat_out = session.cmd_output(mpstat_cmd)
            cpu_stat = dict(
                re.findall(r"Average:\s+(\d+)\s+(\d+\.\d+)", mpstat_out, re.M)
            )
            for cpu_id in plugged_cpu_ids:
                cpu_usage_rate = float(cpu_stat[str(cpu_id)])
                if cpu_usage_rate < 50:
                    test.error(
                        "Stress test on vCPU(%s) failed, usage rate: "
                        "%.2f%%" % (cpu_id, cpu_usage_rate)
                    )
                test.log.info(
                    "Usage rate of vCPU(%s) is: %.2f%%", cpu_id, cpu_usage_rate
                )
        if not vm_arch_name.startswith("s390"):
            for vcpu_dev in vcpu_devices:
                error_context.context(
                    "Hotunplug vcpu device: %s" % vcpu_dev, test.log.info
                )
                vm.hotunplug_vcpu_device(vcpu_dev)
                # Drift the running stress task to other vCPUs
                time.sleep(random.randint(5, 10))
            if not cpu_utils.check_if_vm_vcpus_match_qemu(vm):
                test.fail("Actual number of guest CPUs is not equal to " "expected")
        stress_tool.unload_stress()
        stress_tool.clean()
    else:
        install_path = params["install_path"]
        test_installed_cmd = 'dir "%s" | findstr /I heavyload' % install_path
        heavyload_install()
        error_context.context("Run heavyload inside guest.", test.log.info)
        heavyload_bin = r'"%s\heavyload.exe" ' % install_path
        heavyload_options = [
            "/CPU %d" % vm.get_cpu_count(),
            "/DURATION %d" % (stress_duration // 60),
            "/AUTOEXIT",
            "/START",
        ]
        start_cmd = heavyload_bin + " ".join(heavyload_options)
        stress_tool = BackgroundTest(
            session.cmd, (start_cmd, stress_duration, stress_duration)
        )
        stress_tool.start()
        if not utils_misc.wait_for(stress_tool.is_alive, verify_wait_timeout, first=5):
            test.error("Failed to start heavyload process.")
        stress_tool.join(stress_duration)

    session.close()
