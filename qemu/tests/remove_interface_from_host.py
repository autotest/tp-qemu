"""
Remove tap/interface in host while guest is using it.
"""
import logging
import time
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import utils_net
from virttest import utils_misc
from virttest import utils_test
from virttest import env_process


@error.context_aware
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

    error.context("Login to guest", logging.info)
    vm.wait_for_login(timeout=login_timeout)

    # Step 2, ping should work
    guest_ip = vm.get_address()
    error.context("Get the guest ip %s" % guest_ip, logging.info)

    error.context("Ping test from host to guest, should work",
                  logging.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        raise error.TestFail("Ping failed, status: %s, output: %s"
                             % (status, output))

    host_ifname = vm.get_ifname()
    error.context("Get interface name: %s. " % host_ifname, logging.info)

    # Step 3,4, disable interface and ping should fail
    error.context("Set interface %s down." % host_ifname, logging.info)
    utils_net.ip_link_disable_interface(host_ifname)
    time.sleep(secs_after_iplink_action)

    error.context("After disable the ifname, "
                  "Ping test from host to guest, should fail.",
                  logging.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status == 0:
        raise error.TestFail("Ping should fail, "
                             "status: %s, output: %s"
                             % (status, output))

    # Step 5, enable interface, ping should work
    error.context("Set interface %s up." % host_ifname, logging.info)
    utils_net.ip_link_enable_interface(host_ifname)
    time.sleep(secs_after_iplink_action)

    error.context("After enable the ifname, "
                  "Ping test from host to guest, should work",
                  logging.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        raise error.TestFail("Ping should work, "
                             "status: %s, output: %s"
                             % (status, output))

    # Step 6, delete the interface, qemu should not crash,
    # ping should fail
    error.context("Delete the interface %s." % host_ifname,
                  logging.info)
    utils_net.ip_link_delete_interface(host_ifname)
    time.sleep(secs_after_iplink_action)

    error.context("After delete the ifname, "
                  "VM and qemu should not crash, ping should fail",
                  logging.info)
    vm.verify_alive()
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status == 0:
        raise error.TestFail("Ping should fail, "
                             "status: %s, output: %s"
                             % (status, output))

    # Step 7, shutdown guest, and restart a guest
    error.context("Shutdown the VM.", logging.info)
    vm.monitor.cmd("system_powerdown")

    error.context("Waiting VM to go down "
                  "(system_powerdown monitor cmd)", logging.info)

    if not utils_misc.wait_for(vm.is_dead, 360, 0, 1):
        raise error.TestFail("Guest refuses to go down")
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    # Repeat step 1: Boot a guest
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()

    error.context("Login to guest", logging.info)
    vm.wait_for_login(timeout=login_timeout)

    guest_ip = vm.get_address()
    error.context("Get the guest ip %s" % guest_ip, logging.info)

    # Repeat step 2, ping should work
    error.context("Ping test from host to guest, should work",
                  logging.info)
    status, output = utils_test.ping(guest_ip, 30, timeout=20)
    if status != 0:
        raise error.TestFail("Ping failed, status: %s, output: %s"
                             % (status, output))
