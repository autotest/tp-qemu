import json

from collections import OrderedDict, Counter

from virttest import utils_misc


def parse_usb_topology(params):
    """
    Parse the usb devices topology to the params.

    :param params: Dictionary with the test parameters.
    :return: A list of dictionary ({usb_type_d0: usb_type}) of specified
             usb topology.
    """
    params["usb_devices"] = ""
    # usb topology
    usb_topology = json.loads(params["usb_topology"],
                              object_pairs_hook=OrderedDict)
    parsed_devs = []
    for key, value in usb_topology.iteritems():
        for i in xrange(value):
            params["usb_devices"] += " d%s" % len(parsed_devs)
            usb_type = '{"usb_type_d%s": "%s"}' % (len(parsed_devs), key)
            params.update(json.loads(usb_type))
            parsed_devs.append(json.loads(usb_type))
    return parsed_devs


def collect_usb_dev(params, vm, parsed_devs):
    """
    Collect usb device information of parsed_devs.

    :param params: Dictionary with the test parameters.
    :param vm: Virtual machine object.
    :param parsed_devs: A list of parsed usb devices.
    :return: A list of tuple contains (id, type, port) of a
             usb device.
    """
    devs = []
    for parsed_dev in parsed_devs:
        key = list(parsed_dev.keys())[0]
        usb_dev_id = "usb-%s" % key[9:]
        usb_dev_type = params[parsed_dev[key]]
        usb_dev_port = str(vm.devices.get(usb_dev_id).get_param("port"))
        devs.append((usb_dev_id, usb_dev_type, usb_dev_port))
    return devs


def verify_usb_device_in_monitor(vm, devs):
    """
    Verify usb device information in the qemu monitor.

    This function is using "info usb", it is much more strict verification,
    as it compares the output and devs one by one. However,RHEL does not
    support it.

    :param vm: Virtual machine object.
    :param devs: A list of detailed device information.
    :return: A tuple (status, output) where status is the verification result
             and output is the detail information.
    """
    output = str(vm.monitor.info("usb")).splitlines()
    for dev in devs:
        for chk_str in dev:
            result = next((True for info in output if chk_str in info),
                          False)
            if result is False:
                return (False, "[%s] is not in the monitor info" % chk_str)
    return (True, "all given devices in the monitor info")


def verify_usb_device_in_monitor_qtree(vm, devs):
    """
    Verify usb device information in the qemu monitor.

    This function is using "info qtree" to compatible with RHEL.

    :param vm: Virtual machine object.
    :param devs: A list of detailed device information.
    :return: A tuple (status, output) where status is the verification result
             and output is the detail information.
    """
    output = str(vm.monitor.info("qtree"))
    for dev in devs:
        for chk_str in dev:
            if chk_str not in output:
                return (False, "[%s] is not in the monitor info" % chk_str)
    return (True, "all given devices are verified in the monitor info")


def verify_usb_device_in_guest(params, session, devs):
    """
    Verify usb device information in the guest.

    :param params: Dictionary with the test parameters.
    :param session: Session object.
    :return: A tuple (status, output) where status is the verification result
             and output is the detail information
    """
    def _verify_guest_usb():
        output = session.cmd_output(params["chk_usb_info_cmd"],
                                    float(params["cmd_timeout"]))
        # each dev must in the output
        for dev in devs:
            if dev[1] not in output:
                return False
        # match number of devices
        counter = Counter(dev[1] for dev in devs)
        for k, v in counter.items():
            if output.count(k) != v:
                return False
        return True

    res = utils_misc.wait_for(_verify_guest_usb,
                              float(params["cmd_timeout"]),
                              text="wait for getting guest usb devices info")

    if res:
        return (True, "all given devices are verified in the guest")
    else:
        return (False, "failed to verify usb devices in guest")
