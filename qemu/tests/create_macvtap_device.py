import re

from avocado.utils import process
from virttest import error_context, utils_net, utils_test


def get_macvtap_device_on_ifname(ifname):
    macvtaps = []
    ip_link_out = process.system_output("ip -d link show")
    re_str = r"(\S*)@%s" % ifname
    devices = re.findall(re_str, ip_link_out)
    for device in devices:
        out = process.system_output("ip -d link show %s" % device)
        if "macvtap  mode" in out:
            macvtaps.append(device)
    return macvtaps


@error_context.context_aware
def run(test, params, env):
    """
    create/delete macvtap in host

    1) Verify no other macvtap share the physical network device.
    2) Create a macvtap device in host.
    3) Check configuraton of macvtap device.
    4) Ping out from host with the interface that create macvtap.
    5) Delete the macvtap device create in step 2.
    6) Ping out from host with the interface that create macvtap.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    ifname = params.get("macvtap_base_interface")
    macvtap_mode = params.get("macvtap_mode", "passthru")
    dest_host = params.get("dest_host")
    set_mac = params.get("set_mac", "yes") == "yes"
    macvtaps = []

    if not ifname:
        ifname = params.get("netdst")
    ifname = utils_net.get_macvtap_base_iface(ifname)

    error_context.context(
        "Verify no other macvtap share the physical " "network device.", test.log.info
    )
    macvtap_devices = get_macvtap_device_on_ifname(ifname)
    for device in macvtap_devices:
        process.system_output("ip link delete %s" % device)

    for mode in macvtap_mode.split():
        macvtap_name = "%s_01" % mode
        txt = "Create %s mode macvtap device %s on %s." % (mode, macvtap_name, ifname)
        error_context.context(txt, test.log.info)
        cmd = " ip link add link %s name %s type macvtap mode %s" % (
            ifname,
            macvtap_name,
            mode,
        )
        process.system(cmd, timeout=240)
        if set_mac:
            txt = "Determine and configure mac address of %s, " % macvtap_name
            txt += "Then link up it."
            error_context.context(txt, test.log.info)
            mac = utils_net.generate_mac_address_simple()
            cmd = " ip link set %s address %s up" % (macvtap_name, mac)
            process.system(cmd, timeout=240)

        error_context.context("Check configuraton of macvtap device", test.log.info)
        check_cmd = " ip -d link show %s" % macvtap_name
        try:
            tap_info = process.system_output(check_cmd, timeout=240)
        except process.CmdError:
            err = "Fail to create %s mode macvtap on %s" % (mode, ifname)
            test.fail(err)
        if set_mac:
            if mac not in tap_info:
                err = "Fail to set mac for %s" % macvtap_name
                test.fail(err)
        macvtaps.append(macvtap_name)

    if not dest_host:
        dest_host_get_cmd = "ip route | awk '/default/ { print $3 }'"
        dest_host_get_cmd = params.get("dest_host_get_cmd", dest_host_get_cmd)
        dest_host = process.system_output(dest_host_get_cmd, shell=True).split()[-1]

    txt = "Ping dest host %s from " % dest_host
    txt += "localhost with the interface %s" % ifname
    error_context.context(txt, test.log.info)
    status, output = utils_test.ping(dest_host, 10, interface=ifname, timeout=20)
    ratio = utils_test.get_loss_ratio(output)
    if "passthru" in macvtap_mode:
        ifnames = utils_net.get_host_iface()
        ifnames.remove(ifname)
        test.log.info("ifnames = %s", ifnames)
        ips = []
        for name in ifnames:
            try:
                _ip = utils_net.get_ip_address_by_interface(name)
                if _ip != "127.0.0.1":
                    ips.append(_ip)
            except Exception:
                pass
        test.log.info("ips = %s", ips)
        if not ips:
            if ratio != 100:
                err = "%s did not lost network connection after " % ifname
                err += " creating %s mode macvtap on it." % macvtap_mode
                test.fail(err)
        else:
            err = "%s is not the only network device in host" % ifname
            test.log.debug(err)
    else:
        if ratio != 0:
            err = "Package lost during ping %s from %s " % (dest_host, ifname)
            err += "after creating %s mode macvtap on it." % macvtap_mode
            test.fail(err)

    for name in macvtaps:
        txt = "Delete macvtap device %s on %s." % (name, ifname)
        error_context.context(txt, test.log.info)
        del_cmd = "ip link delete %s" % name
        process.system(del_cmd)
        devices = get_macvtap_device_on_ifname(ifname)
        if name in devices:
            err = "Fail to delete macvtap %s on %s" % (name, ifname)
            test.fail(err)

    test.log.info("dest_host = %s", dest_host)
    txt = "Ping dest host %s from " % dest_host
    txt += "localhost with the interface %s" % ifname
    error_context.context(txt, test.log.info)
    status, output = utils_test.ping(dest_host, 10, interface=ifname, timeout=20)
    if status != 0:
        test.fail("Ping failed, status: %s, output: %s" % (status, output))
    ratio = utils_test.get_loss_ratio(output)
    if ratio != 0:
        err = "Package lost during ping %s from %s " % (dest_host, ifname)
        test.fail(err)
