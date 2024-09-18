import re
import time

import aexpect
from virttest import error_context, utils_misc


@error_context.context_aware
def check_usb_device_monitor(test, params, env):
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Verify USB device in monitor.", test.log.info)
    o = vm.monitor.info("usb")
    if isinstance(o, dict):
        o = o.get("return")
    info_usb_name = params.get("info_usb_name")
    if info_usb_name and (info_usb_name not in o):
        test.fail(
            "Could not find '%s' device, monitor "
            "returns: \n%s" % (params.get("product"), o)
        )


def check_usb_device_guest(session, item, cmd, timeout):
    def __check(session, item, cmd):
        output = session.cmd_output(cmd)
        devices = re.findall(item, output, re.I | re.M)
        if not devices:
            msg = "Could not find item '%s' in guest, " % item
            msg += "Output('%s') in guest: %s" % (cmd, output)
            msgbox.append(msg)
        return devices

    msgbox = []
    kargs = (session, item, cmd)
    devices = utils_misc.wait_for(lambda: __check(*kargs), timeout=timeout)
    return devices, msgbox


@error_context.context_aware
def check_usb_device(test, params, env):
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    check_usb_device_monitor(test, params, env)

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    deviceid_str = params["deviceid_str"]
    vendor_id = params.get("vendor_id")
    product_id = params.get("product_id")
    vendor = params.get("vendor")
    product = params.get("product")

    chk_list = [deviceid_str % (vendor_id, product_id)]
    if vendor:
        chk_list.append(vendor)
    if product:
        chk_list.append(product)

    try:
        session.cmd("dmesg -c")
    except aexpect.ShellCmdError:
        pass

    error_context.context("Verify USB device in guest.")
    cmd = params["chk_usb_info_cmd"]
    for item in chk_list:
        kargs = (session, item, cmd, 5.0)
        exists, msgbox = check_usb_device_guest(*kargs)
        if not exists:
            test.fail(msgbox[0])
    dwprotocols = params.get("dwprotocols", "")
    if dwprotocols:
        cmd = params["chk_specified_usb_info"] % (vendor_id, product_id)
        kargs = (session, dwprotocols, cmd, 5.0)
        exists, msgbox = check_usb_device_guest(*kargs)
        if not exists:
            test.fail(msgbox[0])

    output = ""
    try:
        output = session.cmd("dmesg -c")
        error_context.context("Checking if there is I/O error in dmesg")
    except aexpect.ShellCmdError:
        pass

    io_error_msg = []
    for line in output.splitlines():
        if "error" in line:
            io_error_msg.append(line)

    if io_error_msg:
        e_msg = "Error found in guest's dmesg"
        test.log.error(e_msg)
        for line in io_error_msg:
            test.log.error(line)
        test.fail(e_msg)


@error_context.context_aware
def run(test, params, env):
    """
    KVM usb_basic_check test:
    1) Log into a guest
    2) Verify device(s) work well in guest
    3) Send a reboot command or a system_reset monitor command (optional)
    4) Wait until the guest is up again (optional)
    5) Log into the guest to verify it's up again (optional)
    6) Verify device(s) again after guest reboot (optional)

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _check_dev():
        try:
            check_usb_device(test, params, env)
        except Exception:
            session.close()
            raise

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    error_context.context("Try to log into guest.", test.log.info)
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Verify device(s) before rebooting.")
    _check_dev()

    if params.get("reboot_method"):
        error_context.context("Reboot guest.", test.log.info)
        if params["reboot_method"] == "system_reset":
            time.sleep(int(params.get("sleep_before_reset", 10)))
        session = vm.reboot(session, params["reboot_method"], 0, timeout)

        error_context.context("Verify device(s) after rebooting.")
        _check_dev()

    session.close()
