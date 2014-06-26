import re
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_net, utils_test


def get_macvtap_device_on_ifname(ifname):
    macvtaps = []
    ip_link_out = utils.system_output("ip -d link show")
    re_str = "(\S*)@%s" % ifname
    devices = re.findall(re_str, ip_link_out)
    for device in devices:
        out = utils.system_output("ip -d link show %s" % device)
        if "macvtap  mode" in out:
            macvtaps.append(device)
    return macvtaps


@error.context_aware
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
    macvtap_name = params.get("macvtap_name", "passthru01")
    macvtap_mode = params.get("macvtap_mode", "passthru")
    dest_host = params.get("dest_host")

    if not ifname:
        ifname = params.get("netdst")
    ifname = utils_net.get_macvtap_base_iface(ifname)

    error.context("Verify no other macvtap share the physical network device.",
                  logging.info)
    macvtap_devices = get_macvtap_device_on_ifname(ifname)
    for device in macvtap_devices:
        utils.system_output("ip link delete %s" % device)

    txt = "Create %s mode macvtap device %s on %s." % (macvtap_mode,
                                                       macvtap_name,
                                                       ifname)
    error.context(txt, logging.info)
    cmd = " ip link add link %s name %s type macvtap mode %s" % (ifname,
                                                                 macvtap_name,
                                                                 macvtap_mode)
    utils.system(cmd)

    error.context("Check configuraton of macvtap device", logging.info)
    devices = get_macvtap_device_on_ifname(ifname)
    if macvtap_name not in devices:
        err = "Fail to create %s mode macvtap on %s" % (macvtap_mode, ifname)
        raise error.TestFail(err)

    txt = "Ping dest host from localhost with the interface %s " % ifname
    error.context(txt, logging.info)
    if not dest_host:
        dest_host_get_cmd = "ip route | awk '/default/ { print $3 }'"
        dest_host_get_cmd = params.get("dest_host_get_cmd", dest_host_get_cmd)
        dest_host = utils.system_output(dest_host_get_cmd)
    status, output = utils_test.ping(dest_host, 10,
                                     interface=ifname, timeout=20)
    ratio = utils_test.get_loss_ratio(output)
    if macvtap_mode == "passthru":
        if ratio != 100:
            err = "%s did not lost network connection after creating " % ifname
            err += " %s mode macvtap on it." % macvtap_mode
            raise error.TestFail(err)
    else:
        if ratio != 0:
            err = "Package lost during ping %s from %s " % (dest_host, ifname)
            err += "after creating %s mode macvtap on it." % macvtap_mode
            raise error.TestFail(err)

    txt = "Delete %s mode macvtap device %s on %s." % (macvtap_mode,
                                                       macvtap_name,
                                                       ifname)
    error.context(txt, logging.info)
    del_cmd = "ip link delete %s" % macvtap_name
    utils.system(del_cmd)
    devices = get_macvtap_device_on_ifname(ifname)
    if macvtap_name in devices:
        err = "Fail to delete %s mode macvtap %s on %s" % (macvtap_mode,
                                                           macvtap_name,
                                                           ifname)
        raise error.TestFail(err)

    txt = "Ping dest host from localhost with the interface %s " % ifname
    error.context(txt, logging.info)
    status, output = utils_test.ping(dest_host, 10,
                                     interface=ifname, timeout=20)
    if status != 0:
        raise error.TestFail("Ping failed, status: %s,"
                             " output: %s" % (status, output))
    ratio = utils_test.get_loss_ratio(output)
    if ratio != 0:
        err = "Package lost during ping %s from %s " % (dest_host, ifname)
        raise error.TestFail(err)
