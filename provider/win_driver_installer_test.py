import logging
import time
import os

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_misc
from virttest.utils_windows import virtio_win

from provider import win_driver_utils

LOG_JOB = logging.getLogger('avocado.test')

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
    LOG_JOB.info("Install 'qemu-guest-agent' package in guest.")
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
    LOG_JOB.info("Try to uninstall 'qemu-guest-agent' package.")
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
                          "virtio-win-guest-tools.exe.", LOG_JOB.info)
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
                          "is signed by redhat", LOG_JOB.info)
    status = session.cmd_status(params["signed_check_cmd"])
    if status != 0:
        test.fail('Installer not signed by redhat.')
    if params.get("check_qemufwcfg", "no") == "yes":
        error_context.context("Check if QEMU FWCfg Device is installed.",
                              LOG_JOB.info)
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
        error_context.context("%s Driver Check" % driver_name, LOG_JOB.info)
        inf_path = win_driver_utils.get_driver_inf_path(session, test,
                                                        media_type,
                                                        driver_name)
        expected_ver = session.cmd("type %s | findstr /i /r DriverVer.*=" %
                                   inf_path, timeout=360)
        expected_ver = expected_ver.strip().split(",", 1)[-1]
        if not expected_ver:
            test.error("Failed to find driver version from inf file")
        if driver_name != "qemufwcfg":
            LOG_JOB.info("Target version is '%s'", expected_ver)
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
                          LOG_JOB.info)
    actual_gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]
    if actual_gagent_version != expected_gagent_version:
        test.fail("gagent version is not right, expected is %s but got %s"
                  % (expected_gagent_version, actual_gagent_version))


@error_context.context_aware
def get_viofs_exe(test, params, session):
    """
    Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    error_context.context("Get virtiofs exe full path.", test.log.info)
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

    exe_middle_path = ("{name}\\{arch}" if media_type == "iso"
                       else "{arch}\\{name}").format(name=guest_name,
                                                     arch=guest_arch)
    exe_file_name = "virtiofs.exe"
    exe_find_cmd = 'dir /b /s %s\\%s | findstr "\\%s\\\\"'
    exe_find_cmd %= (viowin_ltr, exe_file_name, exe_middle_path)
    exe_path = session.cmd(exe_find_cmd).strip()
    test.log.info("Found exe file '%s'", exe_path)
    return exe_path


def viofs_svc_create(test, params, session):
    """
    Only for windows guest, to create a virtiofs service
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    viofs_sc_create_cmd = params["viofs_sc_create_cmd"]
    test.log.info("Register virtiofs service in Windows guest.")
    exe_path = get_viofs_exe(test, params, session)
    sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd
                                                         % exe_path)
    if sc_create_s != 0:
        test.fail(
            "Failed to register virtiofs service, output is %s" % sc_create_o)


@error_context.context_aware
def viofs_svc_delete(test, params, session):
    """
    delete the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    viofs_sc_delete_cmd = params["viofs_sc_delete_cmd"]
    error_context.context("Deleting the viofs service...", test.log.info)
    status = session.cmd_status(viofs_sc_delete_cmd)
    if status == 0:
        error_context.context("Done to delete the viofs service...",
                              test.log.info)
    else:
        error_context.context("Failed to delete the viofs service...",
                              test.fail)


@error_context.context_aware
def viofs_svc_start(test, params, seesion):
    """
    start the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    viofs_sc_start_cmd = params["viofs_sc_start_cmd"]
    error_context.context("Trying to start the viofs service...", test.log.info)
    status = seesion.cmd_status(viofs_sc_start_cmd)
    if status == 0:
        error_context.context("Done to start the viofs service.", test.log.info)
    else:
        error_context.context("Failed to start the viofs service...",
                              test.fail)


@error_context.context_aware
def viofs_svc_query(test, params, session):
    """
    query the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    viofs_sc_query_cmd = params["viofs_sc_query_cmd"]
    error_context.context("Query the status of viofs service...", test.log.info)
    output = session.cmd_output(viofs_sc_query_cmd)
    return output


@error_context.context_aware
def viofs_svc_run(test, params, session):
    """
    run the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    output = viofs_svc_query(test, params, session)
    if "not exist as an installed service" not in output:
        error_context.context("Clean virtiofs service registered")
        viofs_svc_delete(test, params, session)
    test.log.info("Register virtiofs service")
    viofs_svc_create(test, params, session)

    test.log.info("Check if virtiofs service is started.")
    output = viofs_svc_query(test, params, session)
    if "RUNNING" not in output:
        viofs_svc_start(test, params, session)
    else:
        test.log.info("Virtiofs service is running.")


def install_winfsp(test, params, session):
    """
    install the winfsp on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    cmd_timeout = params.get_numeric("cmd_timeout", 120)
    install_path = params["install_path"]
    check_installed_cmd = params["check_installed_cmd"] % install_path
    # install winfsp tool
    test.log.info("Install winfsp for windows guest.")
    installed = session.cmd_status(check_installed_cmd) == 0
    if installed:
        test.log.info("Winfsp tool is already installed.")
    else:
        install_cmd = utils_misc.set_winutils_letter(session,
                                                     params["install_cmd"])
        session.cmd(install_cmd, cmd_timeout)
        if not utils_misc.wait_for(lambda: not session.cmd_status(
                check_installed_cmd), 60):
            test.error("Winfsp tool is not installed.")


def get_fs_dest_from_vm(test, params, session):
    """
    get the fs dest from vm( Windows guest only )
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    :return guest_file: the full path of file
    :return fs_dest: the volume letter with colon
    :return volume_letter: the volume letter
    """
    test_file = params.get('test_file', "test_file")
    virtio_fs_disk_label = params.get("fs_target")
    test.log.info("Get Volume letter of virtio fs target, the disk lable is "
                  "%s." % virtio_fs_disk_label)
    vol_con = "VolumeName='%s'" % virtio_fs_disk_label
    volume_letter = utils_misc.wait_for(
        lambda: utils_misc.get_win_disk_vol(session, condition=vol_con),
        timeout=120)
    if volume_letter is None:
        test.fail("Could not get virtio-fs mounted volume letter.")
    fs_dest = "%s:" % volume_letter

    guest_file = os.path.join(fs_dest, test_file)
    test.log.info("The guest file in shared dir is %s", guest_file)
    return guest_file, fs_dest, volume_letter


def basic_io_test(test, params, session):
    """
    basic io test in Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the seesion of guest
    """
    test_file = params.get('test_file', "test_file")
    cmd_dd = params.get("cmd_dd")
    io_timeout = params.get("timeout", 120)
    cmd_md5 = params.get("cmd_md5")
    fs_source = params.get("fs_source_dir")
    base_dir = params.get("fs_source_base_dir",
                          data_dir.get_data_dir())
    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)

    host_data = os.path.join(fs_source, test_file)

    guest_file, fs_dest, volume_letter = get_fs_dest_from_vm(test,
                                                             params,
                                                             session)

    test.log.info("Creating file under %s inside guest." % fs_dest)
    session.cmd(cmd_dd % guest_file, io_timeout)

    guest_file_win = guest_file.replace("/", "\\")
    cmd_md5_vm = cmd_md5 % (volume_letter, guest_file_win)
    md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]

    test.log.info("md5 of the guest file: " + md5_guest)
    md5_host = process.run("md5sum %s" % host_data,
                           io_timeout).stdout_text.strip().split()[0]
    test.log.info("md5 of the host file: " + md5_host)
    if md5_guest != md5_host:
        test.fail('The md5 value of host is not same to guest.')
    else:
        test.log.info("The md5 value of host is as same as md5 value of guest.")
