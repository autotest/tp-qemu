"""
windows driver utility functions.

:copyright: Red Hat Inc.
"""
import logging
import re
import time

from virttest import error_context
from virttest import utils_misc
from virttest.utils_windows import virtio_win, wmic


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
        test.error("Not found devcon.exe, details: %s" % output)
    logging.info("Uninstalling previous installed driver")
    for inf_name in _pnpdrv_info(session, device_name, ["InfName"]):
        uninst_store_cmd = "pnputil /f /d %s" % inf_name
        status, output = session.cmd_status_output(uninst_store_cmd,
                                                   INSTALL_TIMEOUT)
        if status:
            test.error("Failed to uninstall driver '%s' from store, "
                       "details:\n%s" % (driver_name, output))
    uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
    status, output = session.cmd_status_output(uninst_cmd, INSTALL_TIMEOUT)
    # acceptable status: OK(0), REBOOT(1)
    if status > 1:
        test.error("Failed to uninstall driver '%s', details:\n"
                   "%s" % (driver_name, output))


def get_driver_inf_path(session, test, media_type, driver_name):
    """
    Get driver inf path from virtio win iso,such as E:\viofs\2k19\amd64.

    :param session: The guest session object.
    :param test: kvm test object.
    :param media_type: media type.
    :param driver_name: driver name.
    """
    try:
        get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
        get_product_dirname = getattr(virtio_win,
                                      "product_dirname_%s" % media_type)
        get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
    except AttributeError:
        test.error("Not supported virtio win media type '%s'" % media_type)
    viowin_ltr = get_drive_letter(session)
    if not viowin_ltr:
        test.error("Could not find virtio-win drive in guest")
    guest_name = get_product_dirname(session)
    if not guest_name:
        test.error("Could not get product dirname of the vm")
    guest_arch = get_arch_dirname(session)
    if not guest_arch:
        test.error("Could not get architecture dirname of the vm")

    inf_middle_path = ("{name}\\{arch}" if media_type == "iso"
                       else "{arch}\\{name}").format(name=guest_name,
                                                     arch=guest_arch)
    inf_find_cmd = 'dir /b /s %s\\%s.inf | findstr "\\%s\\\\"'
    inf_find_cmd %= (viowin_ltr, driver_name, inf_middle_path)
    inf_path = session.cmd(inf_find_cmd, timeout=OPERATION_TIMEOUT).strip()
    logging.info("Found inf file '%s'", inf_path)
    return inf_path


@error_context.context_aware
def install_driver_by_virtio_media(session, test, devcon_path, media_type,
                                   driver_name,  device_hwid):
    """
    Install driver by virtio media.

    :param session: The guest session object.
    :param test: kvm test object
    :param devcon_path: devcon.exe path.
    :param media_type: media type.
    :param driver_name: driver name.
    :param device_hwid: device hardware id.
    """
    devcon_path = utils_misc.set_winutils_letter(session, devcon_path)
    status, output = session.cmd_status_output("dir %s" % devcon_path,
                                               timeout=OPERATION_TIMEOUT)
    if status:
        test.error("Not found devcon.exe, details: %s" % output)
    error_context.context("Installing target driver", logging.info)
    installed_any = False
    for hwid in device_hwid.split():
        output = session.cmd_output("%s find %s" % (devcon_path, hwid))
        if re.search("No matching devices found", output, re.I):
            continue
        inf_path = get_driver_inf_path(session, test, media_type, driver_name)
        inst_cmd = "%s updateni %s %s" % (devcon_path, inf_path, hwid)
        status, output = session.cmd_status_output(inst_cmd, INSTALL_TIMEOUT)
        # acceptable status: OK(0), REBOOT(1)
        if status > 1:
            test.fail("Failed to install driver '%s', "
                      "details:\n%s" % (driver_name, output))
        installed_any |= True
    if not installed_any:
        test.error("Failed to find target devices "
                   "by hwids: '%s'" % device_hwid)


def install_driver_by_installer(session, test, run_install_cmd,
                                installer_pkg_check_cmd):
    """
    Install driver by installer.

    :param session: The guest session object.
    :param test: kvm test object
    :param run_install_cmd: install cmd.
    :param installer_pkg_check_cmd: installer pkg check cmd.
    """
    run_install_cmd = utils_misc.set_winutils_letter(
                                session, run_install_cmd)
    session.cmd(run_install_cmd)
    if not utils_misc.wait_for(lambda: not session.cmd_status(
                                installer_pkg_check_cmd), 360):
        test.fail("Virtio-win-guest-tools is not installed.")
    time.sleep(60)


def copy_file_to_samepath(session, test, params):
    """
    Copy autoit scripts and installer tool to the same path.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters
    """
    logging.info("Copy autoit scripts and virtio-win-guest-tools.exe "
                 "to the same path.")
    dst_path = r"C:\\"
    vol_virtio_key = "VolumeName like '%virtio-win%'"
    vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
    installer_path = r"%s:\%s" % (vol_virtio, "virtio-win-guest-tools.exe")
    install_script_path = utils_misc.set_winutils_letter(session,
                                                         params["install_script_path"])
    repair_script_path = utils_misc.set_winutils_letter(session,
                                                        params["repair_script_path"])
    uninstall_script_path = utils_misc.set_winutils_letter(session,
                                                           params["uninstall_script_path"])
    src_files = [installer_path, install_script_path, repair_script_path,
                 uninstall_script_path]
    for src_file in src_files:
        copy_cmd = "xcopy %s %s /Y" % (src_file, dst_path)
        status, output = session.cmd_status_output(copy_cmd)
        if status != 0:
            test.error("Copy file error,"
                       " the detailed info:\n%s." % output)
