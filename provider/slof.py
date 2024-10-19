"""
Module for providing common interface to test SLOF component.

Available functions:
 - get_boot_content: Get the specified content of SLOF by reading the serial
                     log.
 - wait_for_loaded: Wait for loading the SLOF.
 - get_booted_devices: Get the device info which tried to load in the SLOF
                       stage.
 - verify_boot_device: Verify whether the vm is booted from the specified
                       device.
 - check_error: Check if there are error info in the SLOF content.
"""

import logging
import os
import re
import time

from virttest import utils_misc

LOG_JOB = logging.getLogger("avocado.test")

START_PATTERN = r"\s+SLOF\S+\s+\*+"
END_PATTERN = r"\s+Successfully loaded$"


def get_boot_content(vm, start_pos=0, start_str=START_PATTERN, end_str=END_PATTERN):
    """
    Get the specified content of SLOF by reading the serial log.

    :param vm: VM object
    :param start_pos: start position which start to read
    :type start_pos: int
    :param start_str: start string pattern
    :type start_str: int
    :param end_str: end string pattern
    :type end_str: str
    :return: content list and next position of the end of the content if found
             the the whole SLOF contents, otherwise return None and the
             position of start string.
    :rtype: tuple(list, int)
    """
    content = []
    start_str_pos = 0
    with open(vm.serial_console_log) as fd:
        for pos, line in enumerate(fd):
            if pos >= start_pos:
                if re.search(start_str, line):
                    start_str_pos = pos
                    content.append(line)
                elif content:
                    content.append(line)
                    if re.search(end_str, line):
                        return content, pos + 1
            else:
                start_str_pos = pos + 1
        else:
            return None, start_str_pos


def wait_for_loaded(
    vm, test, start_pos=0, start_str=START_PATTERN, end_str=END_PATTERN, timeout=300
):
    """
    Wait for loading the SLOF.

    :param vm: VM object
    :param test: kvm test object
    :param start_pos: start position which start to read
    :type start_pos: int
    :param start_str: start string pattern
    :type start_str: int
    :param end_str: end string pattern
    :type end_str: str
    :param timeout: time out for waiting
    :type timeout: float
    :return: content list and next position of the end of the content if found
             the the whole SLOF contents, otherwise return None and the
             position of start string.
    :rtype: tuple(list, int)
    """
    file_timeout = 30
    if not utils_misc.wait_for(
        lambda: os.path.isfile(vm.serial_console_log), file_timeout
    ):
        test.error("No found serial log in %s sec." % file_timeout)

    end_time = timeout + time.time()
    while time.time() < end_time:
        content, start_pos = get_boot_content(vm, start_pos, start_str, end_str)
        if content:
            LOG_JOB.info("Output of SLOF:\n%s", "".join(content))
            return content, start_pos
    test.fail("No found corresponding SLOF info in serial log during %s sec." % timeout)


def get_booted_devices(content):
    """
    Get the device info which tried to load in the SLOF stage.

    :param content: SLOF content
    :type content: list
    :return: device booted
    :rtype: dict
    """
    position = 0
    devices = {}
    for line in content:
        ret = re.search(r"(\s+Trying to load:\s+from:\s)(/.+)(\s+\.\.\.)", line)
        if ret:
            devices[position] = ret.group(2)
            position += 1
    return devices


def verify_boot_device(
    content,
    parent_bus_type,
    child_bus_type,
    child_addr,
    sub_child_addr=None,
    position=0,
):
    """
    Verify whether the vm is booted from the specified device.

    :param content: SLOF content
    :type content: list
    :param parent_bus_type: type of parent bus of device
    :type parent_bus_type: str
    :param child_bus_type: type of bus of device
    :type child_bus_type: str
    :param child_addr: address of device bus
    :type child_addr: str
    :param sub_child_addr: address of device child bus
    :type sub_child_addr: str
    :param position: position in all devices in SLOF content
    :type position: int
    :return: true if booted from the specified device
    :rtype: bool
    """
    pattern = re.compile(r"^0x0?")
    addr = pattern.sub("", child_addr)
    sub_addr = ""
    if sub_child_addr:
        sub_addr = pattern.sub("", sub_child_addr)

    pattern = re.compile(r"/\w+.{1}\w+@")
    devices = get_booted_devices(content)
    for k, v in devices.items():
        if int(k) == position:
            LOG_JOB.info("Position [%d]: %s", k, v)
            break

    if position in devices:
        name = devices[position]
        info = (
            "Check whether the device({0}@{1}@{2}) is the {3} bootable "
            "device.".format(parent_bus_type, child_bus_type, child_addr, position)
        )
        if sub_child_addr:
            info = (
                "Check whether the device({0}@{1}@{2}@{3}) is the {4} "
                "bootable device.".format(
                    parent_bus_type,
                    child_bus_type,
                    child_addr,
                    sub_child_addr,
                    position,
                )
            )
        LOG_JOB.info(info)
        if parent_bus_type == "pci":
            # virtio-blk, virtio-scsi and ethernet device.
            if child_bus_type == "scsi" or child_bus_type == "ethernet":
                if addr == pattern.split(name)[2]:
                    return True
            # pci-bridge, usb device.
            elif child_bus_type == "pci-bridge" or child_bus_type == "usb":
                if (
                    addr == pattern.split(name)[2]
                    and sub_addr == pattern.split(name)[3]
                ):
                    return True
        elif parent_bus_type == "vdevice":
            # v-scsi device, spapr-vlan device.
            if child_bus_type == "v-scsi" or child_bus_type == "l-lan":
                if addr == pattern.split(name)[1]:
                    return True
        else:
            return False
    else:
        LOG_JOB.debug(
            "No such device at position %s in all devices in SLOF contents.", position
        )
        return False


def check_error(test, content):
    """
    Check if there are error info in the SLOF content.

    :param test: kvm test object
    :param content: SLOF content
    :type content: list
    """
    for line in content:
        if re.search(r"error", line, re.IGNORECASE):
            test.fail("Found errors: %s" % line)
    LOG_JOB.info("No errors in SLOF content.")
