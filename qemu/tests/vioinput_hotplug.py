import time

from virttest import error_context

from provider import input_tests


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug/unplug of virtio input device
    1) Boot up w/ one virtio input device
    2) Unplug one virtio input device
    3) Hotplug one virtio input device
    4) Run basic keyboard/mouse test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def hotplug_input_dev(vm, dev):
        error_context.context("Hotplug %s" % dev, test.log.info)
        out, ver_out = vm.devices.simple_hotplug(dev, vm.monitor)
        if not ver_out:
            test.fail("No % device in qtree after hotplug" % dev)
        test.log.info("%s is hotpluged successfully", dev)

    def unplug_input_dev(vm, dev):
        error_context.context("Unplug %s" % dev, test.log.info)
        out, ver_out = vm.devices.simple_unplug(dev, vm.monitor)
        if not ver_out:
            test.fail("Still get %s in qtree after unplug" % dev)
        test.log.info("%s is unpluged successfully", dev)

    def run_subtest(sub_test):
        """
        Run subtest(e.g. rng_bat,reboot,shutdown) when it's not None
        :param sub_test: subtest name
        """
        error_context.context("Run %s subtest" % sub_test, test.log.info)
        wait_time = float(params.get("wait_time", 0.2))
        if sub_test == "keyboard_test":
            input_tests.keyboard_test(test, params, vm, wait_time)
        elif sub_test == "mouse_test":
            input_tests.mouse_test(test, params, vm, wait_time, count=1)

    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    sub_test = params["sub_test"]

    # Hotplug an input device
    new_dev = vm.devices.input_define_by_params(params, params["input_name"])[0]
    hotplug_input_dev(vm, new_dev)
    # For virtio-mouse/tablet device, after new device added,
    # the default working device will change from ps/2 mice to new added mice,
    # so here add 5 sec time to waiting the progress finish.
    time.sleep(5)
    run_subtest(sub_test)
    session = vm.reboot(session)
    # Unplug attached input device
    unplug_input_dev(vm, new_dev)
    session = vm.reboot(session)
    session.close()
