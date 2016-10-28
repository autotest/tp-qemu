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

    def get_rng_id(vm):
        device_list = []
        for device in vm.devices:
            if isinstance(device, qdevices.QDevice):
                if device.get_param("driver") == "virtio-rng-pci":
                    device_list.append(device)
        return device_list

    def hotplug_rng(vm, dev):
        error_context.context("Hotplug %s" % dev, logging.info)
        output = dev.hotplug(vm.monitor)
        time.sleep(5)

        error_context.context("Check %s from qtree after hotplug" % dev,
                              logging.info)
        qtree_output = dev.verify_hotplug(output, vm.monitor)
        if not qtree_output:
            msg = "no % device in qtree after hotplug" % dev
            raise exceptions.TestFail(msg)
        logging.info("%s is hotpluged successfully" % dev)

    def unplug_rng(vm, dev):
        error_context.context("Hot-unplug %s" % dev, logging.info)
        output = dev.unplug(vm.monitor)
        time.sleep(5)

        error_context.context("Check %s from qtree after unplug" % dev,
                              logging.info)
        qtree_output = dev.verify_unplug(output, vm.monitor)
        if not qtree_output:
            msg = "Still get %s in qtree after unplug" % dev
            raise exceptions.TestFail(msg)
        logging.info("%s is unpluged successfully" % dev)

    def restart_rngd(vm):
        if params.get("restart_rngd"):
            session = vm.wait_for_login()
            error_context.context("Restart rngd service", logging.info)
            status, output = session.cmd_status_output("service rngd restart")
            if status != 0:
                raise exceptions.TestError(output)
            session.close()

    def stop_rngd(vm):
        if params.get("stop_rngd"):
            session = vm.wait_for_login()
            error_context.context("Disable rngd service before unplug",
                                  logging.info)
            status, output = session.cmd_status_output(params.get("stop_rngd"))
            if status != 0:
                raise exceptions.TestError(output)
            session.close()

    login_timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 1))
    rng_num = int(params.get("rng_num", 1))
    test_before_hotplug = params.get("test_before_hotplug")
    test_after_hotplug = params.get("test_after_hotplug")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    if test_before_hotplug:
        restart_rngd(vm)
        error_context.context("Run %s before hotplug" % test_before_hotplug)
        utils_test.run_virt_sub_test(test, params, env, test_before_hotplug)

    # Unplug attached rng device
    device_ids = get_rng_id(vm)
    if device_ids:
        stop_rngd(vm)
        time.sleep(5)
        for device in device_ids:
            unplug_rng(vm, device)

    for i in xrange(repeat_times):
        dev_list = []
        error_context.context("Hotplug/unplug rng devices the %s time"
                              % (i+1), logging.info)

        for num in xrange(rng_num):
            vm.devices.set_dirty()
            new_dev = qdevices.QDevice("virtio-rng-pci",
                                       {'id': 'virtio-rng-pci-%d' % num})
            hotplug_rng(vm, new_dev)
            dev_list.append(new_dev)

        # Run test after hotplug
        if test_after_hotplug and i == xrange(repeat_times)[-1]:
            restart_rngd(vm)
            error_context.context("Run %s after hotplug" % test_after_hotplug,
                                  logging.info)
            utils_test.run_virt_sub_test(test, params, env,
                                         test_after_hotplug)

        stop_rngd(vm)
        time.sleep(5)
        for dev in dev_list:
            unplug_rng(vm, dev)
