import json
import logging
from collections import OrderedDict

from virttest import utils_misc

LOG_JOB = logging.getLogger("avocado.test")


def parse_usb_topology(params):
    """
    Parse the usb devices topology to the params.

    :param params: Dictionary with the test parameters.
    :return: A list of dictionary ({usbdev_type_d0: usbdev_type}) of specified
             usb topology.
    """
    params["usb_devices"] = ""
    # usb topology
    usb_topology = json.loads(params["usb_topology"], object_pairs_hook=OrderedDict)
    parsed_devs = []
    for key, value in usb_topology.items():
        for i in range(value):
            params["usb_devices"] += " d%s" % len(parsed_devs)
            usb_type = '{"usbdev_type_d%s": "%s"}' % (len(parsed_devs), key)
            params.update(json.loads(usb_type))
            parsed_devs.append(json.loads(usb_type))
    return parsed_devs


def collect_usb_dev(params, vm, parsed_devs, suffix):
    """
    Collect usb device information of parsed_devs.

    :param params: Dictionary with the test parameters.
    :param vm: Virtual machine object.
    :param parsed_devs: A list of parsed usb devices.
    :params suffix: A string to read different cfg,
                    choose from("for_monitor", "for_guest")
    :return: A list of list contains information of usb devices for
             verification,[id(eg.d0), info(eg.usb-hub), port(eg.1)]
             the info will change based on suffix.
    """

    def _change_dev_info_key(parsed_type, suffix):
        info_key = parsed_type.replace("-", "_")
        return "_".join([info_key, suffix])

    devs = []
    for parsed_dev in parsed_devs:
        key = list(parsed_dev.keys())[0]
        usb_dev_id = "usb-%s" % key[12:]
        usb_dev_info = params[_change_dev_info_key(parsed_dev[key], suffix)]
        usb_dev_port = str(vm.devices.get(usb_dev_id).get_param("port"))
        devs.append([usb_dev_id, usb_dev_info, usb_dev_port])
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
            result = next((True for info in output if chk_str in info), False)
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
        output = session.cmd_output(
            params["chk_usb_info_cmd"], float(params["cmd_timeout"])
        )
        # For usb-hub, '-v' must be used to get the expected usb info.
        # For non usb-hub, refer to 'chk_usb_info_cmd', two situations:
        # '-v' must be used to get expected info
        # '-v' must not be used to avoid duplicate info in output and affect the device count.  # noqa: E501
        if "Hub" in str(devs) and os_type == "linux":
            hub_output = session.cmd_output("lsusb -v", float(params["cmd_timeout"]))
        # each dev must in the output
        for dev in devs:
            if "Hub" in dev[1] and os_type == "linux":
                o = hub_output  # pylint: disable=E0606
            else:
                o = output
            if dev[1] not in o:
                LOG_JOB.info("%s does not exist", dev[1])
                return False
        # match number of devices
        dev_list = [dev[1] for dev in devs]
        dev_nums = dict((i, dev_list.count(i)) for i in dev_list)
        for k, v in dev_nums.items():
            LOG_JOB.info("the number of %s is %s", k, v)
            if "Hub" in k and os_type == "linux":
                o = hub_output
            else:
                o = output
            count = o.count(k)
            if count != v:
                LOG_JOB.info("expected %s %s, got %s in the guest", v, k, count)
                return False
        return True

    os_type = params.get("os_type")
    if os_type == "linux":
        LOG_JOB.info("checking if there is I/O error in dmesg")
        output = session.cmd_output("dmesg | grep -i usb", float(params["cmd_timeout"]))
        for line in output.splitlines():
            if "error" in line or "ERROR" in line:
                return (False, "error found in guest's dmesg: %s " % line)

    res = utils_misc.wait_for(
        _verify_guest_usb,
        float(params["cmd_timeout"]),
        step=5.0,
        text="wait for getting guest usb devices info",
    )

    if res:
        return (True, "all given devices are verified in the guest")
    else:
        return (False, "failed to verify usb devices in guest")
