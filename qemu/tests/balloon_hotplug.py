import random
import re
import time

from virttest import error_context, utils_test
from virttest.qemu_devices import qdevices

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestLinux, BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of balloon devices.

    1) Boot up guest w/o balloon device.
    2) Hoplug balloon device and check hotplug successfully or not.
    3) Install balloon service and check its status in windows guests.
    4) Do memory balloon.
    5) Reboot/shutdown guest after hotplug balloon device(option)
    6) Do memory balloon after guest reboot(option)
    7) Unplug balloon device and check unplug successfully or not.
    8) Reboot/shutdown guest after unplug balloon device(option)

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def run_pm_test(pm_test, plug_type):
        """
        Run pm(reboot/system_reset/shutdown) related test after balloon
        device is hot-plug or hot-unplug
        :param pm_test: power management test name,e.g. reboot/shutdown
        :param plug_type:balloon device plug operation,e.g.hot_plug or hot_unplug
        """
        error_context.context(
            "Run %s test after %s balloon device" % (pm_test, plug_type), test.log.info
        )
        utils_test.run_virt_sub_test(test, params, env, pm_test)

    def enable_balloon_service():
        """
        Install balloon service and check its status in windows guests
        """
        if params["os_type"] != "windows":
            return
        error_context.context(
            "Install and check balloon service in windows " "guest", test.log.info
        )
        session = vm.wait_for_login()
        driver_name = params.get("driver_name", "balloon")
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        balloon_test.configure_balloon_service(session)

        output = balloon_test.operate_balloon_service(session, "status")
        if not re.search(r"running", output.lower(), re.M):
            test.error("Ballooon service status is not running")
        session.close()

    pm_test_after_plug = params.get("pm_test_after_plug")
    pm_test_after_unplug = params.get("pm_test_after_unplug")
    unplug_timeout = params.get("unplug_timeout", 30)
    idx = 0
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    balloon_device = params.get("balloon_device", "virtio-balloon-pci")
    error_context.context("Hotplug and unplug balloon device in a loop", test.log.info)
    for i in range(int(params.get("balloon_repeats", 3))):
        vm.devices.set_dirty()
        new_dev = qdevices.QDevice(
            balloon_device,
            {"id": "balloon%d" % idx},
            parent_bus={"aobject": params.get("balloon_bus", "pci.0")},
        )

        error_context.context(
            "Hotplug balloon device for %d times" % (i + 1), test.log.info
        )
        out = vm.devices.simple_hotplug(new_dev, vm.monitor)
        if out[1] is False:
            test.fail("Failed to hotplug balloon in iteration %s, %s" % (i, out[0]))

        # temporary workaround for migration
        vm.params["balloon"] = "balloon%d" % idx
        vm.params["balloon_dev_devid"] = "balloon%d" % idx
        vm.params["balloon_dev_add_bus"] = "yes"
        devs = vm.devices.get_by_params({"id": "balloon%d" % idx})
        vm.params["balloon_pci_bus"] = devs[0]["bus"]

        if params["os_type"] == "windows":
            balloon_test = BallooningTestWin(test, params, env)
        else:
            balloon_test = BallooningTestLinux(test, params, env)
        min_sz, max_sz = balloon_test.get_memory_boundary()

        enable_balloon_service()

        error_context.context(
            "Check whether balloon device work after hotplug", test.log.info
        )
        balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))

        if pm_test_after_plug:
            run_pm_test(pm_test_after_plug, "hot-plug")
            # run balloon test after reboot,skip followed test if
            # pm_test_after_plug is shutdown
            if vm.is_alive():
                balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
            else:
                return

        if params["os_type"] == "windows":
            time.sleep(10)

        error_context.context(
            "Unplug balloon device for %d times" % (i + 1), test.log.info
        )

        out = vm.devices.simple_unplug(
            devs[0].get_aid(), vm.monitor, timeout=unplug_timeout
        )
        if out[1] is False:
            test.fail("Failed to unplug balloon in iteration %s, %s" % (i, out[0]))
        time.sleep(2)

        if params.get("migrate_after_unplug", "no") == "yes":
            error_context.context(
                "Migrate after hotunplug balloon device", test.log.info
            )
            # temporary workaround for migration
            del vm.params["balloon"]
            del vm.params["balloon_dev_devid"]
            del vm.params["balloon_dev_add_bus"]
            del vm.params["balloon_pci_bus"]
            vm.migrate(float(params.get("mig_timeout", "3600")))

        if pm_test_after_unplug:
            run_pm_test(pm_test_after_unplug, "hot-unplug")
            if not vm.is_alive():
                return

    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        out = vm.devices.simple_hotplug(new_dev, vm.monitor)
        if out[1] is False:
            test.fail("Failed to hotplug balloon at last, " "output is %s" % out[0])
        win_driver_utils.memory_leak_check(vm, test, params)
    error_context.context("Verify guest alive!", test.log.info)
    vm.verify_kernel_crash()
