import logging
import time

from virttest.qemu_devices import qdevices
from virttest import error_context
from virttest import utils_test
from qemu.tests import balloon_check
from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of balloon devices.

    1) Boot up guest w/o balloon device.
    2) Hoplug balloon device and check hotplug successfully or not.
    3) Do memory balloon.
    4) Reboot/shutdown guest after hotplug balloon device(option)
    5) Do memory balloon after guest reboot(option)
    6) Unplug balloon device and check unplug successfully or not.
    7) Reboot/shutdown guest after unplug balloon device(option)

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
        error_context.context("Run %s test after %s balloon device"
                              % (pm_test, plug_type), logging.info)
        utils_test.run_virt_sub_test(test, params, env, pm_test)

    pause = float(params.get("virtio_balloon_pause", 3.0))
    pm_test_after_plug = params.get("pm_test_after_plug")
    pm_test_after_unplug = params.get("pm_test_after_unplug")
    idx = 0
    err = ""
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    balloon_device = params.get("ballon_device", "virtio-balloon-pci")

    error_context.context("Hotplug and unplug balloon device in a loop",
                          logging.info)
    for i in xrange(int(params.get("balloon_repeats", 3))):
        vm.devices.set_dirty()
        new_dev = qdevices.QDevice(balloon_device,
                                   {'id': 'balloon%d' % idx},
                                   parent_bus={'aobject': 'pci.0'})

        error_context.context("Hotplug balloon device for %d times" % (i+1),
                              logging.info)
        out = new_dev.hotplug(vm.monitor)
        if out:
            err += "\nHotplug monitor output: %s" % out
        # Pause
        time.sleep(pause)
        ver_out = new_dev.verify_hotplug(out, vm.monitor)
        if not ver_out:
            err += ("\nDevice is not in qtree %ss after hotplug:\n%s"
                    % (pause, vm.monitor.info("qtree")))

        error_context.context("Check whether balloon device work after hotplug",
                              logging.info)
        balloon_check.run(test, params, env)

        if pm_test_after_plug:
            run_pm_test(pm_test_after_plug, "hot-plug")
            # run balloon test after reboot,skip followed test if
            # pm_test_after_plug is shutdown
            if vm.is_alive():
                balloon_check.run(test, params, env)
            else:
                return

        error_context.context("Unplug balloon device for %d times" % (i+1),
                              logging.info)
        out = new_dev.unplug(vm.monitor)
        if out:
            err += "\nUnplug monitor output: %s" % out
        # Pause
        time.sleep(pause)
        ver_out = new_dev.verify_unplug(out, vm.monitor)
        if not ver_out:
            err += ("\nDevice is still in qtree %ss after unplug:\n%s"
                    % (pause, vm.monitor.info("qtree")))
        if err:
            logging.error(vm.monitor.info("qtree"))
            raise exceptions.TestFail("Error occurred while hotpluging "
                                      "virtio-pci. Iteration %s, monitor "
                                      "output:%s" % (i, err))
        else:
            if pm_test_after_unplug:
                run_pm_test(pm_test_after_unplug, "hot-unplug")
                if not vm.is_alive():
                    return
