import logging
import time

from virttest import error_context
from virttest.qemu_devices import qdevices
from virttest import utils_test
from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug/unplug of rng device
    1) Boot up w/o rng device
    2) Hotplug one or more rng devices
    3) Run random read test after hotplug
    4) Unplug rng devices
    5) Repeat step 2 ~ step4 (option)


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    login_timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 1))
    rng_num = int(params.get("rng_num", 1))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    for i in xrange(repeat_times):
        dev_list = []
        logging.info("Hotplug/unplug rng devices the %sth times", (i+1))

        for num in xrange(rng_num):
            vm.devices.set_dirty()
            new_dev = qdevices.QDevice("virtio-rng-pci",
                                       {'id': 'virtio-rng-pci-%d' % num})
            dev_list.append(new_dev)
            error_context.context("Hotplug %s" % new_dev, logging.info)
            output = new_dev.hotplug(vm.monitor)
            time.sleep(2)

            error_context.context("Check %sfrom qtree after hotplug" % new_dev,
                                  logging.info)
            qtree_output = new_dev.verify_hotplug(output, vm.monitor)
            if not qtree_output:
                msg = "no % device in qtree after hotplug"
                msg += "the %sth time" % (new_dev, i)
                raise exceptions.TestFail(msg)
            logging.info("virtio-rng-pci-%d is hotpluged successfully" % num)
        sub_test = params.get("sub_test_after_hotplug")
        if sub_test:
            utils_test.run_virt_sub_test(test, params, env, sub_test)

        for dev in dev_list:
            error_context.context("Unplug %s" % dev, logging.info)
            output = dev.unplug(vm.monitor)
            time.sleep(2)

            error_context.context("Check rng device from qtree after unplug",
                                  logging.info)
            qtree_output = dev.verify_unplug(output, vm.monitor)
            if not qtree_output:
                msg = "Still get %s in qtree after unplug %s times" % (dev, i)
                raise exceptions.TestFail(msg)
            logging.info("%s is unpluged successfully" % dev)
