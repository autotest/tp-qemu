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
    1) Boot up w/ one rng device
    2) Unplug rng device
    3) reboot/shutdown guest(optional)
    4) Hotplug one or more rng devices
    5) Run random read test after hotplug
    6) Unplug rng devices
    7) Repeat step 4 ~ step 6 (optional)
    8) Hotplug one rng device
    9) Run random read test after hotplug
    10) Reboot/shutdown guest(optional)

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

    def run_subtest(sub_test):
        """
        Run subtest(e.g. rng_bat,reboot,shutdown) when it's not None
        :param sub_test: subtest name
        """
        error_context.context("Run %s subtest" % sub_test)
        utils_test.run_virt_sub_test(test, params, env, sub_test)

    login_timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 1))
    rng_num = int(params.get("rng_num", 1))
    rng_basic_test = params.get("rng_basic_test")
    pm_test_after_plug = params.get("pm_test_after_plug")
    pm_test_after_unplug = params.get("pm_test_after_unplug")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    # run rng test before hot-unplug
    restart_rngd(vm)
    run_subtest(rng_basic_test)

    # Unplug attached rng device
    device_ids = get_rng_id(vm)
    if device_ids:
        stop_rngd(vm)
        time.sleep(5)
        for device in device_ids:
            unplug_rng(vm, device)

    for i in range(repeat_times):
        dev_list = []
        error_context.context("Hotplug/unplug rng devices the %s time"
                              % (i+1), logging.info)

        for num in range(rng_num):
            vm.devices.set_dirty()
            new_dev = qdevices.QDevice("virtio-rng-pci",
                                       {'id': 'virtio-rng-pci-%d' % num})
            hotplug_rng(vm, new_dev)
            dev_list.append(new_dev)

        # run rng test after hotplug
        restart_rngd(vm)
        run_subtest(rng_basic_test)

        # run reboot/shutdown after hotplug
        if pm_test_after_plug:
            run_subtest(pm_test_after_plug)
            # run rng test after reboot,skip followed test if
            # pm_test_after_plug is shutdown
            if vm.is_alive():
                run_subtest(rng_basic_test)
            else:
                return

        stop_rngd(vm)
        time.sleep(5)
        for dev in dev_list:
            unplug_rng(vm, dev)

        # run reboot/shutdown test after hot-unplug
        if pm_test_after_unplug:
            run_subtest(pm_test_after_unplug)
            if not vm.is_alive():
                return
