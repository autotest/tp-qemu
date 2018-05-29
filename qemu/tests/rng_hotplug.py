import logging
import time

from virttest import error_context
from virttest.qemu_devices import qdevices
from virttest import utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug/unplug of rng device
    1) Boot up w/ one rng device
    2) Run random read test
    3) Unplug rng device
    4) Hotplug one or more rng devices
    5) Run random read test after hotplug
    6) Reboot/shutdown/migrate guest(optional)
    7) Unplug rng devices
    8) Reboot/shutdown/migrate guest(optional)
    9) Repeat step 4 ~ step 8 (optional)

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
        out, ver_out = vm.devices.simple_hotplug(dev, vm.monitor)
        if not ver_out:
            msg = "no % device in qtree after hotplug" % dev
            test.fail(msg)
        logging.info("%s is hotpluged successfully" % dev)

    def unplug_rng(vm, dev):
        error_context.context("Hot-unplug %s" % dev, logging.info)
        out, ver_out = vm.devices.simple_unplug(dev, vm.monitor)
        if not ver_out:
            msg = "Still get %s in qtree after unplug" % dev
            test.fail(msg)
        logging.info("%s is unpluged successfully" % dev)

    def restart_rngd(vm):
        if params.get("restart_rngd"):
            session = vm.wait_for_login()
            error_context.context("Restart rngd service", logging.info)
            status, output = session.cmd_status_output("service rngd restart")
            if status != 0:
                test.error(output)
            session.close()

    def stop_rngd(vm):
        if params.get("stop_rngd"):
            session = vm.wait_for_login()
            error_context.context("Disable rngd service before unplug",
                                  logging.info)
            status, output = session.cmd_status_output(params.get("stop_rngd"))
            if status != 0:
                test.error(output)
            session.close()

    def run_subtest(sub_test):
        """
        Run subtest(e.g. rng_bat,reboot,shutdown) when it's not None
        :param sub_test: subtest name
        """
        error_context.context("Run %s subtest" % sub_test)
        utils_test.run_virt_sub_test(test, params, env, sub_test)

    def unplug_all_rngs(vm):
        """
        Hotunplug all attached virtio-rng devices

        :param vm: Virtual machine object.
        """
        devices = get_rng_id(vm)
        if devices:
            stop_rngd(vm)
            time.sleep(5)
            for device in devices:
                unplug_rng(vm, device)

    login_timeout = int(params.get("login_timeout", 360))
    repeat_times = int(params.get("repeat_times", 1))
    rng_num = int(params.get("rng_num", 1))
    rng_basic_test = params.get("rng_basic_test")
    sub_test_after_plug = params.get("sub_test_after_plug")
    sub_test_after_unplug = params.get("sub_test_after_unplug")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    # run rng test before hot-unplug
    restart_rngd(vm)
    run_subtest(rng_basic_test)

    # Unplug attached rng device
    unplug_all_rngs(vm)
    # temporary workaround for migration
    vm.params["virtio_rngs"] = ''

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
            # temporary workaround for migration
            vm.params["virtio_rngs"] += ' rng%d' % num
            vm.params["backend_rng%d" % num] = 'rng-random'

        # run rng test after hotplug
        restart_rngd(vm)
        run_subtest(rng_basic_test)

        # run reboot/shutdown/migration after hotplug
        if sub_test_after_plug:
            run_subtest(sub_test_after_plug)
            # run rng test after reboot,skip followed test if
            # sub_test_after_plug is shutdown
            if vm.is_alive():
                run_subtest(rng_basic_test)
            else:
                return
        if sub_test_after_plug == 'migration':
            # Unplug attached rng device
            unplug_all_rngs(vm)
            # temporary workaround for migration
            vm.params["virtio_rngs"] = ''
        else:
            stop_rngd(vm)
            time.sleep(5)
            for dev in dev_list:
                unplug_rng(vm, dev)

        # run reboot/shutdown/migration test after hot-unplug
        if sub_test_after_unplug:
            run_subtest(sub_test_after_unplug)
            if not vm.is_alive():
                return
