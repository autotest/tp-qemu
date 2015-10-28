import logging
import time

import aexpect

from autotest.client import utils
from autotest.client.shared import error

from virttest import utils_net
from virttest import env_process


def guest_ping(session, dst_ip, count=None, os_type="linux",
               p_size=1472, timeout=360):
    """
    Do ping test in guest
    """
    ping_cmd = "ping"
    if os_type == "linux":
        if count:
            ping_cmd += " -c %s" % count
        ping_cmd += " -s %s %s" % (p_size, dst_ip)
    else:
        if not count:
            ping_cmd += " -t "
        ping_cmd += " -l %s %s" % (p_size, dst_ip)
    try:
        logging.debug("Ping dst vm with cmd: '%s'" % ping_cmd)
        session.cmd(ping_cmd, timeout=timeout)
    except aexpect.ShellTimeoutError, err:
        if count:
            raise error.TestError("Error during ping guest ip, %s" % err)


def wait_guest_network_up(session, dst_ip, timeout=180):
    txt = "Check whether guest network up by ping %s " % dst_ip
    error.context(txt, logging.info)
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            guest_ping(session, dst_ip, count=1, timeout=timeout)
        except aexpect.ShellCmdError:
            continue
        return True
    return False


@error.context_aware
def run(test, params, env):
    """
    QEMU 'multi macvtap devices' test

    1) Create and up multi macvtap devices in setting mode.
    2) change the limitations of fd to 10240 in host.
    3) Boot multi guest with macvtap and at least one guest use fd whick bigger
       than 1024.
    4) Ping from guests to an external host for 100 counts.
    5) Shutdown all guests.
    6) Delete all macvtap interfaces.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    macvtap_num = int(params.get("macvtap_num", "5000"))
    macvtap_mode = params.get("macvtap_mode", "vepa")
    timeout = int(params.get("login_timeout", 360))
    ping_count = int(params.get("ping_count", 100))
    netdst = params.get("netdst")
    macvtap_ifnames = []
    default_host = params.get("default_ext_host")
    ext_host_get_cmd = params.get("ext_host_get_cmd")
    try:
        ext_host = utils.system_output(ext_host_get_cmd)
    except error.CmdError:
        logging.warn("Can't get specified host with cmd '%s',"
                     " Fallback to default host '%s'",
                     ext_host_get_cmd, default_host)
        ext_host = default_host
    try:
        txt = "Create and up %s macvtap devices in setting mode." % macvtap_num
        error.context(txt, logging.info)
        for num in xrange(macvtap_num):
            mac = utils_net.generate_mac_address_simple()
            ifname = "%s_%s" % (macvtap_mode, num)
            tapfd = utils_net.create_and_open_macvtap(ifname, macvtap_mode,
                                                      1, netdst, mac)
            check_cmd = "ip -d link show %s" % ifname
            output = utils.system_output(check_cmd)
            logging.debug(output)
            macvtap_ifnames.append(ifname)
        vms = params.get("vms").split()
        params["start_vm"] = "yes"
        error.context("Boot multi guest with macvtap", logging.info)
        for vm_name in vms:
            env_process.preprocess_vm(test, params, env, vm_name)
        for vm_name in vms:
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            session = vm.wait_for_serial_login(timeout=timeout)
            if wait_guest_network_up(session, ext_host, timeout=timeout):
                txt = " Ping from guests to %s for %s counts." % (ext_host,
                                                                  ping_count)
                error.context(txt, logging.info)
                guest_ping(session, ext_host, 100)
            else:
                ipconfig_cmd = params.get("ipconfig_cmd", "ifconfig -a")
                out = session.cmd(ipconfig_cmd)
                msg = "Could not ping %s successful after %ss."
                msg += "Guest network status (%s): %s" % (ipconfig_cmd, out)
                raise error.TestFail(msg)
    finally:
        error.context("Delete all macvtap interfaces.", logging.info)
        for ifname in macvtap_ifnames:
            del_cmd = "ip link delete %s" % ifname
            utils.system(del_cmd, ignore_status=True)
