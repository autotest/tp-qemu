from virttest import error_context, utils_net
from virttest.utils_test.qemu import MemoryHotplugTest


@error_context.context_aware
def run(test, params, env):
    """
    Test vDPA control virtqueue

    1) Boot a guest and qemu must have space for more memory slots
    2) Change mac address 2^16-1 times
    3) Hotplug 1G memory to update device
    4) Try to update the mac again and it should mac address can be changed
       normally

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    size_mem = params.get("size_mem")
    change_cmd = params["change_cmd"]
    target_mem = params["target_mem"]
    old_mac = vm.get_mac_address(0)
    new_mac = vm.virtnet.generate_mac_address(0)
    interface = utils_net.get_linux_ifname(session_serial, old_mac)
    test.log.info("change mac address 2^16-1 times")
    change_times = params.get_numeric("change_times")
    for i in range(change_times):
        output = session_serial.cmd_output_safe(change_cmd % (new_mac, interface))
        if output:
            test.fail("Mac address changed failed,print error info: %s" % output)
    output = vm.process.get_output()
    if output:
        test.error("Qemu output error info: %s" % output)
    test.log.info("Finished change mac address 2^16-1 times")
    test.log.info("Hotplug %s memory to update device", size_mem)
    hotplug_mem = MemoryHotplugTest(test, params, env)
    hotplug_mem.hotplug_memory(vm=vm, name=target_mem)
    test.log.info("Try to update the mac again")
    session_serial.cmd_output_safe(change_cmd % (old_mac, interface))
    output = session_serial.cmd_output_safe("ifconfig | grep -i %s" % old_mac)
    if old_mac in output:
        test.log.info("Mac address change successfully, net restart...")
    else:
        test.fail("Mac address can not be changed")
    session_serial.close()
