import time

from virttest import error_context
from virttest.utils_test import qemu

from provider import netperf


@error_context.context_aware
def run(test, params, env):
    """
    Driver in use test:
    1) boot guest with the device.
    2) enable and check driver verifier in guest.
    3) run netperf test.
    4) run main test during netperf test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def shutdown():
        """
        shutdown the vm by shell command
        """
        shutdown_command = params.get("shutdown_command")
        session.sendline(shutdown_command)
        error_context.context(
            "waiting VM to go down (shutdown shell cmd)", test.log.info
        )
        if not vm.wait_for_shutdown(360):
            test.fail("Guest refuses to go down")

    def stop_continue():
        """
        stop the vm and then resume it test
        """
        error_context.base_context("Stop the VM", test.log.info)
        vm.pause()
        error_context.context("Verify the status of VM is 'paused'", test.log.info)
        if vm.verify_status("paused") is False:
            test.error("VM status is not paused")
        vm.resume()
        error_context.context("Verify the status of VM is 'running'", test.log.info)
        if vm.verify_status("running") is False:
            test.error("VM status is not running")

    def reboot():
        """
        reboot the vm by shell command
        """
        vm.reboot()

    def nic_hotplug():
        """
        hotplug/hotunplug a nic to the vm test
        """
        pci_model = params.get("pci_model")
        netdst = params.get("netdst", "virbr0")
        nettype = params.get("nettype", "bridge")
        nic_hotplug_count = params.get_numeric("nic_hotplug_count", 10)
        for i in range(1, nic_hotplug_count):
            nic_name = "hotadded%s" % i
            vm.hotplug_nic(
                nic_model=pci_model,
                nic_name=nic_name,
                netdst=netdst,
                nettype=nettype,
                queues=params.get("queues"),
            )
            time.sleep(3)
            vm.hotunplug_nic(nic_name)
            time.sleep(3)

    netkvm_sub_test = params["netkvm_sub_test"]
    driver = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver)
    driver_running = params.get("driver_running", driver_verifier)
    timeout = int(params.get("login_timeout", 360))

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    error_context.context("Boot guest with %s device" % driver, test.log.info)

    session = vm.wait_for_login(timeout=timeout)
    qemu.windrv_verify_running(session, test, driver_running)
    session = qemu.setup_win_driver_verifier(session, driver_verifier, vm)
    session.close()
    error_context.context("Start netperf test", test.log.info)
    netperf_test = netperf.NetperfTest(params, vm)
    if netperf_test.start_netperf_test():
        error_context.context(
            "Start %s test during netperf test" % netkvm_sub_test, test.log.info
        )
        eval("%s()" % netkvm_sub_test)
    else:
        test.fail("Failed to start netperf test")
