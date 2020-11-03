import logging
import time

from virttest import error_context
from virttest import utils_misc

from provider import win_driver_utils

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
                    '"PCI\\VEN_1AF4&DEV_1004" "PCI\\VEN_1AF4&DEV_1048"',
                    '"ACPI\\QEMU0002"']

device_name_list = ["Red Hat VirtIO Ethernet Adapter", "VirtIO RNG Device",
                    "VirtIO Serial Driver", "VirtIO Balloon Driver",
                    "QEMU PVPanic Device", "VirtIO Input Driver",
                    "VirtIO FS Device", "Red Hat VirtIO SCSI controller",
                    "Red Hat VirtIO SCSI pass-through controller",
                    "QEMU FWCfg Device"]


def install_gagent(session, test, qemu_ga_pkg, gagent_install_cmd,
                   gagent_pkg_info_cmd):
    """
    Install guest agent.

    :param session: The guest session object.
    :param test: kvm test object
    :param qemu_ga_pkg: guest agent pkg name.
    :param gagent_install_cmd: guest agent install command.
    :param gagent_pkg_info_cmd: guest agent pkg info check command.
    """
    logging.info("Install 'qemu-guest-agent' package in guest.")
    vol_virtio_key = "VolumeName like '%virtio-win%'"
    vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
    qemu_ga_pkg_path = r"%s:\%s\%s" % (vol_virtio, "guest-agent", qemu_ga_pkg)
    gagent_install_cmd = gagent_install_cmd % qemu_ga_pkg_path
    s_inst, o_inst = session.cmd_status_output(gagent_install_cmd)
    if s_inst != 0:
        test.fail("qemu-guest-agent install failed,"
                  " the detailed info:\n%s." % o_inst)
    gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]
    return gagent_version


def uninstall_gagent(session, test, gagent_uninstall_cmd):
    """
    Uninstall guest agent.

    :param session: The guest session object.
    :param test: kvm test object
    :param gagent_uninstall_cmd: guest agent uninstall command.
    """
    logging.info("Try to uninstall 'qemu-guest-agent' package.")
    s, o = session.cmd_status_output(gagent_uninstall_cmd)
    if s:
        test.fail("Could not uninstall qemu-guest-agent package ")


def win_uninstall_all_drivers(session, test, params):
    """
    Uninstall all drivers from windows guests.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters.
    """
    devcon_path = params["devcon_path"]
    if params.get("check_qemufwcfg", "no") == "yes":
        driver_name_list.append('qemufwcfg')
    for driver_name, device_name, device_hwid in zip(driver_name_list,
                                                     device_name_list,
                                                     device_hwid_list):
        win_driver_utils.uninstall_driver(session, test, devcon_path,
                                          driver_name, device_name,
                                          device_hwid)


@error_context.context_aware
def install_test_with_screen_on_desktop(vm, session, test, run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=None):
    """
    Install test when guest screen on desktop.

    :param vm: vm object
    :param session: The guest session object.
    :param test: kvm test object.
    :param run_install_cmd: install cmd.
    :param installer_pkg_check_cmd: installer pkg check cmd.
    :param copy_files_params: copy files params.
    """
    error_context.context("Install virtio-win drivers via "
                          "virtio-win-guest-tools.exe.", logging.info)
    vm.send_key('meta_l-d')
    time.sleep(30)
    if copy_files_params:
        win_driver_utils.copy_file_to_samepath(session, test,
                                               copy_files_params)
    win_driver_utils.install_driver_by_installer(session, test,
                                                 run_install_cmd,
                                                 installer_pkg_check_cmd)


@error_context.context_aware
def win_installer_test(session, test, params):
    """
    Windows installer related check.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters.
    """
    error_context.context("Check if virtio-win-guest-too.exe "
                          "is signed by redhat", logging.info)
    status = session.cmd_status(params["signed_check_cmd"])
    if status != 0:
        test.fail('Installer not signed by redhat.')
    if params.get("check_qemufwcfg", "no") == "yes":
        error_context.context("Check if QEMU FWCfg Device is installed.",
                              logging.info)
        device_name = "QEMU FWCfg Device"
        chk_cmd = params["vio_driver_chk_cmd"] % device_name
        status = session.cmd_status(chk_cmd)
        if status != 0:
            test.fail("QEMU FWCfg Device not installed")


@error_context.context_aware
def driver_check(session, test, params):
    """
    Check driver version and sign.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters.
    """
    chk_timeout = int(params.get("chk_timeout", 240))
    media_type = params["virtio_win_media_type"]
    wrong_ver_driver = []
    not_signed_driver = []
    if params.get("check_qemufwcfg", "no") == "yes":
        driver_name_list.append('qemufwcfg')
    for driver_name, device_name in zip(driver_name_list, device_name_list):
        error_context.context("%s Driver Check" % driver_name, logging.info)
        inf_path = win_driver_utils.get_driver_inf_path(session, test,
                                                        media_type,
                                                        driver_name)
        expected_ver = session.cmd("type %s | findstr /i /r DriverVer.*=" %
                                   inf_path, timeout=360)
        expected_ver = expected_ver.strip().split(",", 1)[-1]
        if not expected_ver:
            test.error("Failed to find driver version from inf file")
        if driver_name != "qemufwcfg":
            logging.info("Target version is '%s'", expected_ver)
            ver_list = win_driver_utils._pnpdrv_info(session, device_name,
                                                     ["DriverVersion"])
            if expected_ver not in ver_list:
                wrong_ver_driver.append(driver_name)
        chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
        chk_output = session.cmd_output(chk_cmd, timeout=chk_timeout)
        if "FALSE" in chk_output:
            not_signed_driver.append(driver_name)
        elif "TRUE" not in chk_output:
            test.error("Device %s is not found in guest" % device_name)
    if wrong_ver_driver:
        test.fail("%s not the expected driver version" % wrong_ver_driver)
    if not_signed_driver:
        test.fail("%s not digitally signed!" % not_signed_driver)


@error_context.context_aware
def check_gagent_version(session, test, gagent_pkg_info_cmd,
                         expected_gagent_version):
    """
    Check whether guest agent version is right.

    :param session: The guest session object.
    :param test: kvm test object
    :param gagent_pkg_info_cmd: guest-agent pkg info check command.
    :param expected_gagent_version: expected gagent version.
    """
    error_context.context("Check if gagent version is correct.",
                          logging.info)
    actual_gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]
    if actual_gagent_version != expected_gagent_version:
        test.fail("gagent version is not right, expected is %s but got %s"
                  % (expected_gagent_version, actual_gagent_version))
