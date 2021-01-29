"""
windows driver utility functions.

:copyright: Red Hat Inc.
"""
import logging

from virttest import utils_misc
from virttest.utils_windows import wmic


QUERY_TIMEOUT = 360
INSTALL_TIMEOUT = 360
OPERATION_TIMEOUT = 120


def _pnpdrv_info(session, name_pattern, props=None):
    """Get the driver props eg: InfName"""
    cmd = wmic.make_query("path win32_pnpsigneddriver",
                          "DeviceName like '%s'" % name_pattern,
                          props=props, get_swch=wmic.FMT_TYPE_LIST)
    return wmic.parse_list(session.cmd(cmd, timeout=QUERY_TIMEOUT))


def uninstall_driver(session, test, devcon_path, driver_name,
                     device_name, device_hwid):
    """
    Uninstall driver.

    :param session: The guest session object.
    :param test: kvm test object
    :param devcon_path: devcon.exe path.
    :param driver_name: driver name.
    :param device_name: device name.
    :param device_hwid: device hardware id.
    """
    devcon_path = utils_misc.set_winutils_letter(session, devcon_path)
    status, output = session.cmd_status_output("dir %s" % devcon_path,
                                               timeout=OPERATION_TIMEOUT)
    if status:
        test.error("Not found devcon.exe, details: %s", output)
    logging.info("Uninstalling previous installed driver")
    for inf_name in _pnpdrv_info(session, device_name, ["InfName"]):
        uninst_store_cmd = "pnputil /f /d %s" % inf_name
        status, output = session.cmd_status_output(uninst_store_cmd,
                                                   INSTALL_TIMEOUT)
        if status:
            test.error("Failed to uninstall driver '%s' from store, "
                       "details:\n%s", driver_name, output)
    uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
    status, output = session.cmd_status_output(uninst_cmd, INSTALL_TIMEOUT)
    # acceptable status: OK(0), REBOOT(1)
    if status > 1:
        test.error("Failed to uninstall driver '%s', details:\n"
                   "%s", driver_name, output)
