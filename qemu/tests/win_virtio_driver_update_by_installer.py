import logging
import time
import re

from virttest import error_context
from virttest import utils_misc
from virttest import data_dir
from virttest.utils_windows import virtio_win, wmic


QUERY_TIMEOUT = 360
INSTALL_TIMEOUT = 360
OPERATION_TIMEOUT = 120


def _pnpdrv_info(session, name_pattern, props=None):
    cmd = wmic.make_query("path win32_pnpsigneddriver",
                          "DeviceName like '%s'" % name_pattern,
                          props=props, get_swch=wmic.FMT_TYPE_LIST)
    return wmic.parse_list(session.cmd(cmd, timeout=QUERY_TIMEOUT))


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Create shared directories on the host.
    2) Run virtiofsd daemons on the host.
    3) Boot guest with all virtio device.
    4) Install driver from previous virtio-win.iso.
       Or virtio-win-guest-tool.
    5) upgrade driver via virtio-win-guest-tools.exe
    6) Verify the qemu-ga version match expected version.
    7) Run driver signature check command in guest.
       Verify target driver.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    def change_virtio_media(cdrom_virtio):
        """
        change iso for virtio-win
        :param cdrom_virtio: iso file
        """
        virtio_iso = utils_misc.get_path(data_dir.get_data_dir(),
                                         cdrom_virtio)
        logging.info("Changing virtio iso image to '%s'" % virtio_iso)
        vm.change_media("drive_virtio", virtio_iso)

    def get_driver_inf_path(session, driver_name):
        """
        Get driver inf path from virtio win iso,such as E:\viofs\2k19\amd64.

        :param session: The guest session object.
        :param driver_name: driver name.
        """
        media_type = params["virtio_win_media_type"]
        try:
            get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
            get_product_dirname = getattr(virtio_win,
                                          "product_dirname_%s" % media_type)
            get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
        except AttributeError:
            test.error("Not supported virtio win media type '%s'", media_type)
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

    def uninstall_driver(session, driver_name, device_name, device_hwid):
        """
        Uninstall driver.

        :param session: The guest session object.
        :param driver_name: driver name.
        :param device_name: device name.
        :param device_hwid: device hardware id.
        """
        error_context.context("Uninstalling previous installed driver",
                              logging.info)
        for inf_name in _pnpdrv_info(session, device_name, ["InfName"]):
            uninst_store_cmd = "pnputil /f /d %s" % inf_name
            status, output = session.cmd_status_output(uninst_store_cmd,
                                                       inst_timeout)
            if status:
                test.error("Failed to uninstall driver '%s' from store, "
                           "details:\n%s" % (driver_name, output))

        uninst_cmd = "%s remove %s" % (devcon_path, device_hwid)
        status, output = session.cmd_status_output(uninst_cmd, inst_timeout)
        # acceptable status: OK(0), REBOOT(1)
        if status > 1:
            test.error("Failed to uninstall driver '%s', details:\n"
                       "%s" % (driver_name, output))

    def install_driver(session, driver_name,  device_hwid):
        """
        Install driver.

        :param session: The guest session object.
        :param driver_name: driver name.
        :param device_hwid: device hardware id.
        """
        error_context.context("Installing target driver", logging.info)
        installed_any = False
        for hwid in device_hwid.split():
            output = session.cmd_output("%s find %s" % (devcon_path, hwid))
            if re.search("No matching devices found", output, re.I):
                continue
            inst_cmd = "%s updateni %s %s" % (devcon_path, inf_path, hwid)
            status, output = session.cmd_status_output(inst_cmd, inst_timeout)
            # acceptable status: OK(0), REBOOT(1)
            if status > 1:
                test.fail("Failed to install driver '%s', "
                          "details:\n%s" % (driver_name, output))
            installed_any |= True
        if not installed_any:
            test.error("Failed to find target devices "
                       "by hwids: '%s'" % device_hwid)

    inst_timeout = int(params.get("driver_install_timeout", INSTALL_TIMEOUT))
    chk_timeout = int(params.get("chk_timeout", 240))
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]

    # qemu version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    devcon_path = utils_misc.set_winutils_letter(session,
                                                 params["devcon_path"])
    status, output = session.cmd_status_output("dir %s" % devcon_path,
                                               timeout=OPERATION_TIMEOUT)
    if status:
        test.error("Not found devcon.exe, details: %s" % output)

    error_context.context("Install 'qemu-guest-agent' package in guest.",
                          logging.info)
    vol_virtio_key = "VolumeName like '%virtio-win%'"
    vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
    qemu_ga_pkg_path = r"%s:\%s\%s" % (vol_virtio, "guest-agent", qemu_ga_pkg)
    gagent_install_cmd = params["gagent_install_cmd"] % qemu_ga_pkg_path
    s_inst, o_inst = session.cmd_status_output(gagent_install_cmd)
    if s_inst != 0:
        test.error("qemu-guest-agent install failed,"
                   " the detailed info:\n%s." % o_inst)
    expected_gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]

    error_context.context("Try to uninstall 'qemu-guest-agent' package.",
                          logging.info)
    s, o = session.cmd_status_output(gagent_uninstall_cmd)
    if s:
        test.error("Could not uninstall qemu-guest-agent package "
                   "in guest', detail: '%s'" % o)

    change_virtio_media(params["cdrom_virtio_downgrade"])

    # copy autoit scripts and installer tool to the same path
    error_context.context("Copy autoit scripts and virtio-win-guest-tools.exe "
                          "to the same path.", logging.info)
    dst_path = r"C:\\"
    installer_path = r"%s:\%s" % (vol_virtio, "virtio-win-guest-tools.exe")
    install_script_path = utils_misc.set_winutils_letter(session,
                                                         params["install_script_path"])
    src_files = [installer_path, install_script_path]
    for src_file in src_files:
        copy_cmd = "xcopy %s %s /Y" % (src_file, dst_path)
        status, output = session.cmd_status_output(copy_cmd)
        if status != 0:
            test.error("Copy file error,"
                       " the detailed info:\n%s." % output)

    driver_name_list = ['netkvm', 'viorng', 'vioser',
                        'balloon', 'pvpanic', 'vioinput',
                        'viofs', 'viostor', 'vioscsi']

    device_hwid_list = ['"PCI\\VEN_1AF4&DEV_1000" "PCI\\VEN_1AF4&DEV_1041"',
                        '"PCI\\VEN_1AF4&DEV_1005" "PCI\\VEN_1AF4&DEV_1044"',
                        '"PCI\\VEN_1AF4&DEV_1003" "PCI\\VEN_1AF4&DEV_1043"',
                        '"PCI\\VEN_1AF4&DEV_1002" "PCI\\VEN_1AF4&DEV_1045"',
                        '"ACPI\\QEMU0001"', '"PCI\\VEN_1AF4&DEV_1052"',
                        '"PCI\\VEN_1AF4&DEV_105A"',
                        '"PCI\\VEN_1AF4&DEV_1001" "PCI\\VEN_1AF4&DEV_1042"',
                        '"PCI\\VEN_1AF4&DEV_1004" "PCI\\VEN_1AF4&DEV_1048"']

    device_name_list = ["Red Hat VirtIO Ethernet Adapter", "VirtIO RNG Device",
                        "VirtIO Serial Driver", "VirtIO Balloon Driver",
                        "QEMU PVPanic Device", "VirtIO Input Driver",
                        "VirtIO FS Device", "Red Hat VirtIO SCSI controller",
                        "Red Hat VirtIO SCSI pass-through controller"]

    if params.get("update_from_previous_installer", "no") == "yes":

        for driver_name, device_name, device_hwid in zip(driver_name_list,
                                                         device_name_list, device_hwid_list):
            uninstall_driver(session, driver_name, device_name, device_hwid)
        session = vm.reboot(session)
        vm.send_key('meta_l-d')
        time.sleep(30)
        error_context.context("install virtio driver from previous installer",
                              logging.info)
        error_context.context("Install virtio-win drivers via "
                              "virtio-win-guest-tools.exe.", logging.info)
        run_install_cmd = utils_misc.set_winutils_letter(
                                 session, params["run_install_cmd"])
        session.cmd(run_install_cmd)
        if not utils_misc.wait_for(lambda: not session.cmd_status(
                                   installer_pkg_check_cmd), 120):
            test.fail("Virtio-win-guest-tools is not installed.")
        time.sleep(30)
    else:
        for driver_name, device_name, device_hwid in zip(driver_name_list,
                                                         device_name_list, device_hwid_list):
            # downgrade iso have no viofs yet
            if driver_name == "viofs":
                continue
            uninstall_driver(session, driver_name, device_name, device_hwid)
            session = vm.reboot(session)
            inf_path = get_driver_inf_path(session, driver_name)
            install_driver(session, driver_name,  device_hwid)
        error_context.context("Install 'qemu-guest-agent' package in guest.",
                              logging.info)
        s_inst, o_inst = session.cmd_status_output(gagent_install_cmd)
        if s_inst != 0:
            test.fail("qemu-guest-agent install failed,"
                      " the detailed info:\n%s." % o_inst)

    error_context.context("Upgrade virtio driver to original",
                          logging.info)
    change_virtio_media(params["cdrom_virtio"])
    vm.send_key('meta_l-d')
    time.sleep(30)
    src_files = [installer_path, install_script_path]
    for src_file in src_files:
        copy_cmd = "xcopy %s %s /Y" % (src_file, dst_path)
        status, output = session.cmd_status_output(copy_cmd)
        if status != 0:
            test.error("Copy file error,"
                       " the detailed info:\n%s." % output)

    error_context.context("Install virtio-win drivers via "
                          "virtio-win-guest-tools.exe.", logging.info)
    run_install_cmd = utils_misc.set_winutils_letter(
                             session, params["run_install_cmd"])
    session.cmd(run_install_cmd)
    if not utils_misc.wait_for(lambda: not session.cmd_status(
                               installer_pkg_check_cmd), 120):
        test.fail("Virtio-win-guest-tools is not installed.")

    time.sleep(60)
    session = vm.reboot(session)
    error_context.context("Check if gagent version is correct.",
                          logging.info)
    actual_gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]
    if actual_gagent_version != expected_gagent_version:
        test.fail("gagent version is not right, expected is %s but got %s"
                  % (expected_gagent_version, actual_gagent_version))

    wrong_ver_driver = []
    not_signed_driver = []
    for driver_name, device_name in zip(driver_name_list, device_name_list):
        error_context.context("%s Driver Check" % driver_name, logging.info)
        inf_path = get_driver_inf_path(session, driver_name)
        expected_ver = session.cmd("type %s | findstr /i /r DriverVer.*=" %
                                   inf_path, timeout=OPERATION_TIMEOUT)
        expected_ver = expected_ver.strip().split(",", 1)[-1]
        if not expected_ver:
            test.error("Failed to find driver version from inf file")
        logging.info("Target version is '%s'", expected_ver)
        ver_list = _pnpdrv_info(session, device_name, ["DriverVersion"])
        if expected_ver not in ver_list:
            wrong_ver_driver.append(driver_name)
        chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
        chk_output = session.cmd_output(chk_cmd, timeout=chk_timeout)
        if "FALSE" in chk_output:
            not_signed_driver.append(driver_name)
        elif "TRUE" in chk_output:
            pass
        else:
            test.error("Device %s is not found in guest" % device_name)
    if wrong_ver_driver:
        test.fail("%s not the expected driver version" % wrong_ver_driver)
    if not_signed_driver:
        test.fail("%s not digitally signed!" % not_signed_driver)

    session.close()
