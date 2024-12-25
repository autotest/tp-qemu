"""
windows driver utility functions.

:copyright: Red Hat Inc.
"""

import logging
import os
import re
import time

import aexpect
from virttest import data_dir, error_context, utils_misc, utils_test
from virttest.utils_version import VersionInterval
from virttest.utils_windows import system, virtio_win, wmic

LOG_JOB = logging.getLogger("avocado.test")


QUERY_TIMEOUT = 360
INSTALL_TIMEOUT = 360
OPERATION_TIMEOUT = 120

driver_info_dict = {
    "netkvm": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1000" "PCI\\VEN_1AF4&DEV_1041"',
        "device_name": "Red Hat VirtIO Ethernet Adapter",
    },
    "viorng": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1005" "PCI\\VEN_1AF4&DEV_1044"',
        "device_name": "VirtIO RNG Device",
    },
    "vioser": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1003" "PCI\\VEN_1AF4&DEV_1043"',
        "device_name": "VirtIO Serial Driver",
    },
    "balloon": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1002" "PCI\\VEN_1AF4&DEV_1045"',
        "device_name": "VirtIO Balloon Driver",
    },
    "pvpanic": {"hwid": '"ACPI\\QEMU0001"', "device_name": "QEMU PVPanic Device"},
    "vioinput": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1052"',
        "device_name": "VirtIO Input Driver",
    },
    "viofs": {"hwid": '"PCI\\VEN_1AF4&DEV_105A"', "device_name": "VirtIO FS Device"},
    "viostor": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1001" "PCI\\VEN_1AF4&DEV_1042"',
        "device_name": "Red Hat VirtIO SCSI controller",
    },
    "vioscsi": {
        "hwid": '"PCI\\VEN_1AF4&DEV_1004" "PCI\\VEN_1AF4&DEV_1048"',
        "device_name": "Red Hat VirtIO SCSI pass-through controller",
    },
    "fwcfg": {
        "hwid": '"ACPI\\VEN_QEMU&DEV_0002" "ACPI\\QEMU0002"',
        "device_name": "QEMU FWCfg Device",
    },
    "viomem": {
        "hwid": r'"PCI\VEN_1AF4&DEV_1002" "PCI\VEN_1AF4&DEV_1058"',
        "device_name": "VirtIO Viomem Driver",
    },
}


def _pnpdrv_info(session, name_pattern, props=None):
    """Get the driver props eg: InfName"""
    cmd = wmic.make_query(
        "path win32_pnpsigneddriver",
        "DeviceName like '%s'" % name_pattern,
        props=props,
        get_swch=wmic.FMT_TYPE_LIST,
    )
    return wmic.parse_list(session.cmd(cmd, timeout=QUERY_TIMEOUT))


def uninstall_driver(session, test, devcon_path, driver_name, device_name, device_hwid):
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
    status, output = session.cmd_status_output(
        "dir %s" % devcon_path, timeout=OPERATION_TIMEOUT
    )
    if status:
        test.error("Not found devcon.exe, details: %s" % output)
    LOG_JOB.info("Uninstalling previous installed driver")
    # find the inf name and remove the repeated one
    inf_list_all = _pnpdrv_info(session, device_name, ["InfName"])
    inf_list = list(set(inf_list_all))

    # pnputil flags available starting in Windows 10,
    #  version 1607, build 14393 later
    build_ver = system.version(session).split(".")[2]
    if int(build_ver) > 14393:
        uninst_store_cmd = "pnputil /delete-driver %s /uninstall /force" % inf_list[0]
    else:
        uninst_store_cmd = "pnputil /f /d %s" % inf_list[0]
    status, output = session.cmd_status_output(uninst_store_cmd, INSTALL_TIMEOUT)
    # for viostor and vioscsi, they need system reboot
    # acceptable status: OK(0), REBOOT(3010)
    if status not in (0, 3010):
        test.error(
            "Failed to uninstall driver '%s' from store, "
            "details:\n%s" % (driver_name, output)
        )
    uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
    status, output = session.cmd_status_output(uninst_cmd, INSTALL_TIMEOUT)
    # acceptable status: OK(0), REBOOT(1)
    if status > 1:
        test.error(
            "Failed to uninstall driver '%s', details:\n" "%s" % (driver_name, output)
        )


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
        get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
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

    inf_middle_path = (
        "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
    ).format(name=guest_name, arch=guest_arch)
    inf_find_cmd = 'dir /b /s %s\\%s.inf | findstr "\\%s\\\\"'
    inf_find_cmd %= (viowin_ltr, driver_name, inf_middle_path)
    inf_path = session.cmd(inf_find_cmd, timeout=OPERATION_TIMEOUT).strip()
    LOG_JOB.info("Found inf file '%s'", inf_path)
    return inf_path


@error_context.context_aware
def install_driver_by_virtio_media(
    session, test, devcon_path, media_type, driver_name, device_hwid
):
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
    status, output = session.cmd_status_output(
        "dir %s" % devcon_path, timeout=OPERATION_TIMEOUT
    )
    if status:
        test.error("Not found devcon.exe, details: %s" % output)
    error_context.context("Installing target driver", LOG_JOB.info)
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
            test.fail(
                "Failed to install driver '%s', " "details:\n%s" % (driver_name, output)
            )
        installed_any |= True
    if not installed_any:
        test.error("Failed to find target devices " "by hwids: '%s'" % device_hwid)


def autoit_installer_check(params, session):
    """
    Check if AUTOIT3.EXE is running.
    :param params: the dict used for parameters
    :param session: The guest session object.
    :return: True if it is running.
    """
    autoit_check_cmd = params.get(
        "autoit_check_cmd", "tasklist |findstr /i autoit3_.*exe"
    )
    try:
        return session.cmd_status(autoit_check_cmd) == 0
    except (
        aexpect.ShellTimeoutError,
        aexpect.ShellProcessTerminatedError,
        aexpect.ShellStatusError,
    ):
        LOG_JOB.info("VM is rebooting...")
        return False


def run_installer(vm, session, test, params, run_installer_cmd):
    """
    Install/uninstall/repair virtio-win drivers and qxl,spice and
    qemu-ga-win by installer.
    If installer(virtio-win) version is in [1.9.37, 1.9.40]
    then installer itself will restart vm for installation and
    uninstallation function; otherwise there is no need to reboot guest.
    While for repair function, installer itself always restart vm by
    itself;

    :param vm: vm object.
    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters
    :param run_installer_cmd: install/uninstall/repair cmd.
    :return session: a new session after restart of installer
    """
    cdrom_virtio = params["cdrom_virtio"]
    installer_restart_version = params.get(
        "installer_restart_version", "[1.9.37.0, 1.9.40.0]"
    )
    cdrom_virtio_path = os.path.basename(
        utils_misc.get_path(data_dir.get_data_dir(), cdrom_virtio)
    )
    match = re.search(r"virtio-win-(\d+\.\d+(?:\.\d+)?-\d+)", cdrom_virtio_path)
    cdrom_virtio_version = re.sub("-", ".", match.group(1))
    # run installer cmd
    run_installer_cmd = utils_misc.set_winutils_letter(session, run_installer_cmd)
    session.cmd(run_installer_cmd)

    if not utils_misc.wait_for(
        lambda: not autoit_installer_check(params, session), 240, 2, 2
    ):
        test.fail("Autoit exe stop there for 240s," " please have a check.")
    restart_con_ver = cdrom_virtio_version in VersionInterval(installer_restart_version)
    restart_con_repair = "repair" in run_installer_cmd
    if restart_con_ver or restart_con_repair:
        # Wait for vm re-start by installer itself
        if not utils_misc.wait_for(lambda: not session.is_responsive(), 120, 5, 5):
            test.fail(
                "The previous session still exists,"
                "seems that the vm doesn't restart."
            )
        session = vm.wait_for_login(timeout=360)
    # for the early virtio-win instller, rebooting is needed.
    if cdrom_virtio_version in VersionInterval("(,1.9.37.0)"):
        session = vm.reboot(session)
    return session


def remove_driver_by_msi(session, vm, params):
    """
    Remove virtio_win drivers by msi.

    :param session: The guest session object
    :param vm:
    :param params: the dict used for parameters
    :return: a new session after restart os
    """
    media_type = params.get("virtio_win_media_type", "iso")
    get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
    drive_letter = get_drive_letter(session)
    msi_path = drive_letter + "\\" + params["msi_name"]
    msi_uninstall_cmd = params["msi_uninstall_cmd"] % msi_path
    vm.send_key("meta_l-d")
    # msi uninstall cmd will restart os.
    session.cmd(msi_uninstall_cmd)
    time.sleep(15)
    return vm.wait_for_login(timeout=360)


def copy_file_to_samepath(session, test, params):
    """
    Copy autoit scripts and installer tool to the same path.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters
    """
    LOG_JOB.info(
        "Copy autoit scripts and virtio-win-guest-tools.exe " "to the same path."
    )
    dst_path = r"C:\\"
    vol_virtio_key = "VolumeName like '%virtio-win%'"
    vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)

    installer_path = r"%s:\%s" % (vol_virtio, "virtio-win-guest-tools.exe")
    install_script_path = utils_misc.set_winutils_letter(
        session, params["install_script_path"]
    )
    repair_script_path = utils_misc.set_winutils_letter(
        session, params["repair_script_path"]
    )
    uninstall_script_path = utils_misc.set_winutils_letter(
        session, params["uninstall_script_path"]
    )
    src_files = [
        installer_path,
        install_script_path,
        repair_script_path,
        uninstall_script_path,
    ]
    if params.get("msi_name"):
        msi_path = r"%s:\%s" % (vol_virtio, params["msi_name"])
        uninstall_msi_script_path = utils_misc.set_winutils_letter(
            session, params["uninstall_msi_script_path"]
        )
        src_files.extend([msi_path, uninstall_msi_script_path])

    for src_file in src_files:
        copy_cmd = "xcopy %s %s /Y" % (src_file, dst_path)
        status, output = session.cmd_status_output(copy_cmd)
        if status != 0:
            test.error("Copy file error," " the detailed info:\n%s." % output)


def enable_driver(session, test, cmd):
    """
    Enable driver.

    :param session: The guest session object
    :param test: kvm test object
    :param cmd: Driver enable cmd
    """
    cmd = utils_misc.set_winutils_letter(session, cmd)
    status, output = session.cmd_status_output(cmd)
    if status != 0:
        test.fail("failed to enable driver, %s" % output)


def disable_driver(session, vm, test, cmd):
    """
    Disable driver.

    :param session: The guest session object
    :param vm: vm object
    :param test: kvm test object
    :param cmd: Driver disable command
    """
    cmd = utils_misc.set_winutils_letter(session, cmd)
    status, output = session.cmd_status_output(cmd)
    if status != 0:
        if "reboot" in output:
            session = vm.reboot(session)
        else:
            test.fail("failed to disable driver, %s" % output)
    return session


def get_device_id(session, test, driver_name):
    """
    Get device id from guest.

    :param session: The guest session object
    :param test: kvm test object
    :param driver_name: Driver name
    """
    device_name = driver_info_dict[driver_name]["device_name"]
    device_hwid = driver_info_dict[driver_name]["hwid"]

    output = _pnpdrv_info(session, device_name, ["DeviceID"])
    # workaround for viostor/vioscsi to get data device id
    device_id = output[0]
    device_id = "&".join(device_id.split("&amp;"))
    find_devices = False
    for hwid in device_hwid.split():
        hwid = hwid.split('"')[1]
        if hwid in device_id:
            find_devices = True
    if not find_devices:
        test.fail("Didn't find driver info from guest %s" % output)
    return device_id


def load_driver(session, test, params, load_method="enable"):
    """
    Load driver.

    :param session: The guest session object
    :param test: kvm test object
    :param params: the dict used for parameters
    :param load_method: Load driver method
    """
    driver_name = params["driver_name"]
    devcon_path = params["devcon_path"]
    if load_method != "enable":
        params.get("virtio_win_media_type", "iso")

        device_hwid = driver_info_dict[driver_name]["hwid"]
        install_driver_by_virtio_media(session, test, devcon_path, device_hwid)
    else:
        device_id = get_device_id(session, test, driver_name)
        cmd = '%s enable "@%s"' % (devcon_path, device_id)
        enable_driver(session, test, cmd)
    utils_test.qemu.windrv_verify_running(session, test, driver_name)


def unload_driver(session, vm, test, params, load_method="enable"):
    """
    Unload driver.

    :param session: The guest session object
    :param vm: vm object
    :param test: kvm test object
    :param params: the dict used for parameters
    :param load_method: Load driver method
    """
    driver_name = params["driver_name"]
    devcon_path = params["devcon_path"]
    if load_method != "enable":
        device_name = driver_info_dict[driver_name]["device_name"]
        device_hwid = driver_info_dict[driver_name]["hwid"]
        uninstall_driver(
            session, test, devcon_path, driver_name, device_name, device_hwid
        )
    else:
        device_id = get_device_id(session, test, driver_name)
        cmd = '%s disable "@%s"' % (devcon_path, device_id)
        session = disable_driver(session, vm, test, cmd)
    return session


def memory_leak_check(vm, test, params, load_method="enable"):
    """
    In order to let the driver verifier to catch memory leaks, driver
    should be unloaded after driver function.Note that if want to use
    this function, driver verifier should be enabled before driver function.

    :param vm: vm object
    :param test: kvm test object
    :param params: the dict used for parameters
    :param load_method: Load driver method
    """
    session = vm.wait_for_login()
    session = unload_driver(session, vm, test, params, load_method)
    time.sleep(10)
    if vm.is_alive() is False:
        test.fail(
            "VM is not alive after uninstall driver,"
            "please check if it is a memory leak"
        )
    if load_method != "enable":
        session = vm.reboot(session)
    load_driver(session, test, params, load_method)
    session.close()
