"""
Remove tap/interface in host while guest is using it.
"""

import logging
import time

from virttest import env_process, error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    While the guest is using the interface, delete it.

    1) Boot a guest with network card.
    2) Ping host from guest, should return successfully.
    3) In host, disable the interface which the guest uses.
    4) Ping host would fail.
    5) Enable the interface again, ping would work.
    6) Remove the interface from host,
       qemu would not crash, the guest would not crash too.
    7) Shutdown guest, and repeat step1 to step2. Guest would recover.
    """
    secs_after_iplink_action = 3
    login_timeout = int(params.get("login_timeout", 360))

    # Step 1: Boot a guest
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()

    error_context.context("Login to guest", test.log.info)
    vm.wait_for_login(timeout=login_timeout)

    # Step 2, ping should work
    guest_ip = vm.get_address()
    error_context.context("Get the guest ip %s" % guest_ip, test.log.info)

    error_context.context("Ping test from host to guest, should work", test.log.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        test.fail("Ping failed, status: %s, output: %s" % (status, output))

    host_ifname_name = vm.get_ifname()
    error_context.context("Get interface name: %s. " % host_ifname_name, test.log.info)
    host_ifname = utils_net.Interface(host_ifname_name)

    # Step 3,4, disable interface and ping should fail
    error_context.context("Set interface %s down." % host_ifname_name, test.log.info)
    host_ifname.down()
    time.sleep(secs_after_iplink_action)

    error_context.context(
        "After disable the ifname, " "Ping test from host to guest, should fail.",
        test.log.info,
    )
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status == 0:
        test.fail("Ping should fail, status: %s, output: %s" % (status, output))

    # Step 5, enable interface, ping should work
    error_context.context("Set interface %s up." % host_ifname_name, test.log.info)
    host_ifname.up()
    time.sleep(secs_after_iplink_action)

    error_context.context(
        "After enable the ifname, " "Ping test from host to guest, should work",
        test.log.info,
    )
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        test.fail("Ping should work, status: %s, output: %s" % (status, output))

    # Step 6, delete the interface, qemu should not crash,
    # ping should fail
    error_context.context("Delete the interface %s." % host_ifname_name, test.log.info)
    host_ifname.dellink()
    time.sleep(secs_after_iplink_action)

    error_context.context(
        "After delete the ifname, " "VM and qemu should not crash, ping should fail",
        test.log.info,
    )
    vm.verify_alive()
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status == 0:
        test.fail("Ping should fail, status: %s, output: %s" % (status, output))

    # Step 7, shutdown guest, and restart a guest
    error_context.context("Shutdown the VM.", test.log.info)
    session = vm.wait_for_serial_login()
    shutdown_cmd = params.get("shutdown_command", "shutdown")
    logging.debug("Shutdown guest with command %s", shutdown_cmd)
    session.sendline(shutdown_cmd)

    error_context.context("Waiting VM to go down", test.log.info)

    if not utils_misc.wait_for(vm.is_dead, 360, 0, 1):
        test.fail("Guest refuses to go down")
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    # Repeat step 1: Boot a guest
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()

    error_context.context("Login to guest", test.log.info)
    vm.wait_for_login(timeout=login_timeout)

    guest_ip = vm.get_address()
    error_context.context("Get the guest ip %s" % guest_ip, test.log.info)

    # Repeat step 2, ping should work
    error_context.context("Ping test from host to guest, should work", test.log.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        test.fail("Ping failed, status: %s, output: %s" % (status, output))
