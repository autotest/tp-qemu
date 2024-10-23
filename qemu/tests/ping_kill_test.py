import time

import aexpect
from avocado.utils import process
from virttest import error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Run two vms on one host. Disable network on the second vm and send
    infinite ping -b -s 1472 on the first vm.
    After a while (6h) try to shutdown first vm nicely.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def kill_and_check(vm):
        """
        Kill the vm and check vm is dead
        """
        qemu_pid = vm.get_pid()
        cmd = "kill -9 %s" % qemu_pid
        process.system(cmd)
        if not vm.wait_until_dead(timeout=10):
            test.fail("VM is not dead, 10s after '%s' sent." % cmd)
        test.log.info("Vm is dead as expected")

    def guest_ping(session, dst_ip, count=None):
        """
        Do ping test in guest
        """
        os_type = params.get("os_type")
        packetsize = params.get("packetsize", 1472)
        test_runner = session.sendline
        if count:
            test_runner = session.cmd
        ping_cmd = "ping"
        if os_type == "linux":
            if count:
                ping_cmd += " -c %s" % count
            ping_cmd += " -s %s %s" % (packetsize, dst_ip)
        else:
            if not count:
                ping_cmd += " -t "
            ping_cmd += " -l %s %s" % (packetsize, dst_ip)
        try:
            test.log.debug("Ping dst vm with cmd: '%s'", ping_cmd)
            test_runner(ping_cmd)
        except aexpect.ShellTimeoutError as err:
            if count:
                test.error("Error during ping guest ip, %s" % err)

    def ping_is_alive(session):
        """
        Check whether ping is alive, if ping process is alive return True,
        else return False
        """
        os_type = params.get("os_type")
        if os_type == "linux":
            return not session.cmd_status("pidof ping")
        else:
            return not session.cmd_status("tasklist | findstr /I ping.exe")

    def manage_guest_nic(session, ifname, disabled=True):
        """
        Enable or disable guest nic
        """
        os_type = params.get("os_type", "linux")
        if os_type == "linux":
            shut_down_cmd = "ifconfig %s " % ifname
            if disabled:
                shut_down_cmd += " down"
            else:
                shut_down_cmd += " up"
            session.cmd_output_safe(shut_down_cmd)
        else:
            if disabled:
                utils_net.disable_windows_guest_network(session, ifname)
            else:
                utils_net.enable_windows_guest_network(session, ifname)

    error_context.context("Init boot the vms")
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    check_sess = vm.wait_for_login(timeout=login_timeout)

    dsthost = params.get("dsthost", "vm2")
    if dsthost not in params.get("vms"):
        test.cancel("This test must boot two vms")
    dst_vm = env.get_vm(dsthost)
    dst_vm.verify_alive()
    dst_vm.wait_for_login(timeout=login_timeout)
    dst_ip = dst_vm.get_address()
    session_serial = dst_vm.wait_for_serial_login(timeout=login_timeout)

    try:
        error_context.context("Ping dst guest", test.log.info)
        guest_ping(session, dst_ip, count=4)

        error_context.context("Disable the dst guest nic interface", test.log.info)
        macaddress = dst_vm.get_mac_address()
        if params.get("os_type") == "linux":
            ifname = utils_net.get_linux_ifname(session_serial, macaddress)
        else:
            ifname = utils_net.get_windows_nic_attribute(
                session_serial, "macaddress", macaddress, "netconnectionid"
            )
        manage_guest_nic(session_serial, ifname)

        error_context.context("Ping dst guest after disabling it's nic", test.log.info)
        ping_timeout = float(params.get("ping_timeout", 21600))
        guest_ping(session, dst_ip)
        # This test need do infinite ping for a long time(6h)
        test.log.info("Waiting for %s(S) before next step", ping_timeout)
        end_time = time.time() + ping_timeout
        while time.time() < end_time:
            try:
                if not ping_is_alive(check_sess):
                    test.cancel("Ping process is not alive")
            except Exception as err:
                test.error("Check ping status error '%s'" % err)
            else:
                time.sleep(60)

        error_context.context("Kill the guest after ping", test.log.info)
        kill_and_check(vm)

    finally:
        if session_serial:
            manage_guest_nic(session_serial, ifname, False)
            session_serial.close()
        if session:
            session.close()
