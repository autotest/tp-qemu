import logging
import time

from virttest.qemu_devices import qdevices
from virttest import error_context

from qemu.tests import balloon_check


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of balloon devices.

    1) Boot up guest w/o balloon device.
    2) Hoplug balloon device and check hotplug successfully or not.
    3) Do memory balloon (Do migration if needed).
    4) Unplug balloon device and check unplug successfully or not.
    5) Do migration if needed.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    pause = float(params.get("virtio_balloon_pause", 3.0))
    idx = 0
    err = ""
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Hotplug and unplug balloon device in a loop",
                          logging.info)
    for i in xrange(int(params.get("balloon_repeats", 3))):
        vm.devices.set_dirty()
        new_dev = qdevices.QDevice("virtio-balloon-pci",
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

        vm.params["balloon"] = "balloon%d" % idx
        vm.params["balloon_dev_devid"] = "balloon%d" % idx
        vm.params["balloon_dev_add_bus"] = "yes"

        error_context.context("Check whether balloon device work after hotplug",
                              logging.info)
        balloon_check.run(test, params, env)

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

        if params.get("migrate_after_unplug", "no") == "yes":
            del vm.params["balloon"]
            del vm.params["balloon_dev_devid"]
            del vm.params["balloon_dev_add_bus"]
            vm.migrate(float(params.get("mig_timeout", "3600")))

        if err:
            logging.error(vm.monitor.info("qtree"))
            test.fail("Error occurred while hotpluging "
                      "virtio-pci. Iteration %s, monitor "
                      "output:%s" % (i, err))
