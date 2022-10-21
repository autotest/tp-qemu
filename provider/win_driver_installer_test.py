import logging
import re
import time
import os

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_disk
from virttest import utils_misc
from virttest.utils_windows import virtio_win

from provider import win_driver_utils
from provider.storage_benchmark import generate_instance

LOG_JOB = logging.getLogger('avocado.test')


driver_name_list = ['viorng', 'viostor', 'vioscsi',
                    'balloon', 'viofs', 'vioser',
                    'pvpanic', 'netkvm', 'vioinput']

device_hwid_list = ['"PCI\\VEN_1AF4&DEV_1005" "PCI\\VEN_1AF4&DEV_1044"',
                    '"PCI\\VEN_1AF4&DEV_1001" "PCI\\VEN_1AF4&DEV_1042"',
                    '"PCI\\VEN_1AF4&DEV_1004" "PCI\\VEN_1AF4&DEV_1048"',
                    '"PCI\\VEN_1AF4&DEV_1002" "PCI\\VEN_1AF4&DEV_1045"',
                    '"PCI\\VEN_1AF4&DEV_105A"',
                    '"PCI\\VEN_1AF4&DEV_1003" "PCI\\VEN_1AF4&DEV_1043"',
                    '"ACPI\\QEMU0001"',
                    '"PCI\\VEN_1AF4&DEV_1000" "PCI\\VEN_1AF4&DEV_1041"',
                    '"PCI\\VEN_1AF4&DEV_1052"',
                    '"ACPI\\QEMU0002"']

device_name_list = ["VirtIO RNG Device", "Red Hat VirtIO SCSI controller",
                    "Red Hat VirtIO SCSI pass-through controller",
                    "VirtIO Balloon Driver", "VirtIO FS Device",
                    "VirtIO Serial Driver", "QEMU PVPanic Device",
                    "Red Hat VirtIO Ethernet Adapter", "VirtIO Input Driver",
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
    global driver_name_list, device_name_list
    chk_timeout = int(params.get("chk_timeout", 240))
    media_type = params["virtio_win_media_type"]
    wrong_ver_driver = []
    not_signed_driver = []
    if params.get("check_qemufwcfg", "no") == "yes":
        driver_name_list.append('qemufwcfg')
    if params.get("driver_name"):
        driver_name_list = [params["driver_name"]]
        device_name_list = [params["device_name"]]
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
def get_drive_letter(test, vm, img_size):
    """
    Get drive letter.

    :param test: kvm test object.
    :param vm: vm object.
    :param img_size: image size.
    """
    session = vm.wait_for_login()
    error_context.context("Format data disk", test.log.info)
    disk_index = utils_disk.get_windows_disks_index(session, img_size)
    if not disk_index:
        test.error("Failed to get the disk index of size %s" % img_size)
    if not utils_disk.update_windows_disk_attributes(session, disk_index):
        test.error("Failed to enable data disk %s" % disk_index)
    drive_letter_list = utils_disk.configure_empty_windows_disk(
        session, disk_index[0], img_size)
    if not drive_letter_list:
        test.error("Failed to format the data disk")
    return drive_letter_list[0]


@error_context.context_aware
def rng_test(test, params, vm):
    """
    Generate random data for windows.

    :param test: kvm test object.
    :param params: the dict used for parameters.
    :param vm: vm object.
    """
    session = vm.wait_for_login()
    read_rng_cmd = params['read_rng_cmd']
    read_rng_cmd = utils_misc.set_winutils_letter(session, read_rng_cmd)
    error_context.context("Read virtio-rng device to get random number",
                          LOG_JOB.info)
    output = session.cmd_output(read_rng_cmd)
    if len(re.findall(r'0x\w', output, re.M)) < 2:
        test.fail("Unable to read random numbers "
                  "from guest: %s" % output)


@error_context.context_aware
def iozone_test(test, params, vm, images):
    """
    Run iozone inside guest.

    :param test: kvm test object.
    :param params: the dict used for parameters.
    :param vm: vm object.
    :param img_size: image size.
    """
    iozone = generate_instance(params, vm, 'iozone')

    for img in images.split():
        drive_letter = get_drive_letter(test, vm, params['image_size_%s' % img])
        try:
            error_context.context("Running IOzone command on guest",
                                  LOG_JOB.info)
            iozone.run(params['iozone_cmd_opitons'] % drive_letter)
        finally:
            iozone.clean()


@error_context.context_aware
def get_viofs_exe_path(test, params, session):
    """
    Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
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


def create_viofs_service(test, params, session):
    """
    Only for windows guest, to create a virtiofs service
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_create_cmd_default = 'sc create VirtioFsSvc binpath="%s" ' \
                                  'start=auto  ' \
                                  'depend="WinFsp.Launcher/VirtioFsDrv" ' \
                                  'DisplayName="Virtio FS Service"'
    viofs_sc_create_cmd = params.get("viofs_sc_create_cmd",
                                     viofs_sc_create_cmd_default)
    test.log.info("Create virtiofs service in Windows guest.")
    exe_path = get_viofs_exe_path(test, params, session)
    sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd
                                                         % exe_path)
    if sc_create_s != 0:
        test.fail(
            "Failed to create virtiofs service, output is %s" % sc_create_o)


@error_context.context_aware
def delete_viofs_serivce(test, params, session):
    """
    Delete the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_delete_cmd = params.get("viofs_sc_delete_cmd",
                                     "sc delete VirtioFsSvc")
    error_context.context("Deleting the viofs service...", test.log.info)
    output = query_viofs_service(test, params, session)
    if "not exist as an installed service" in output:
        test.log.info("The viofs service was NOT found at the guest."
                      " Skipping delete...")
    else:
        status = session.cmd_status(viofs_sc_delete_cmd)
        if status == 0:
            test.log.info("Done to delete the viofs service...")
        else:
            test.error("Failed to delete the viofs service...")


@error_context.context_aware
def start_viofs_service(test, params, session):
    """
    Start the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_start_cmd = params.get("viofs_sc_start_cmd",
                                    "sc start VirtioFsSvc")
    error_context.context("Start the viofs service...", test.log.info)
    status = session.cmd_status(viofs_sc_start_cmd)
    if status == 0:
        test.log.info("Done to start the viofs service.")
    else:
        test.error("Failed to start the viofs service...")


@error_context.context_aware
def query_viofs_service(test, params, session):
    """
    Query the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    :return output: the output of cmd return
    """
    viofs_sc_query_cmd = params.get("viofs_sc_query_cmd",
                                    "sc query VirtioFsSvc")
    error_context.context("Query the status of viofs service...",
                          test.log.info)
    return session.cmd_output(viofs_sc_query_cmd)


@error_context.context_aware
def run_viofs_service(test, params, session):
    """
    Run the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    install_winfsp(test, params, session)
    output = query_viofs_service(test, params, session)
    if "not exist as an installed service" in output:
        test.log.info("The virtiofs service is NOT created.")
        test.log.info("Create virtiofs service")
        create_viofs_service(test, params, session)

    test.log.info("Check if virtiofs service is started.")
    output = query_viofs_service(test, params, session)
    if "RUNNING" not in output:
        start_viofs_service(test, params, session)
    else:
        test.log.info("Virtiofs service is running.")


@error_context.context_aware
def stop_viofs_service(test, params, session):
    """
    Stop the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_stop_cmd = params.get("viofs_sc_stop_cmd", "sc stop VirtioFsSvc")
    session.cmd(viofs_sc_stop_cmd)

    test.log.info("Query status of the virtiofs service...")
    output = query_viofs_service(test, params, session)
    if "RUNNING" in output:
        test.error("Virtiofs service is still running.")
    else:
        test.log.info("Virtiofs service is stopped.")


def install_winfsp(test, params, session):
    """
    Install the winfsp on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    cmd_timeout = params.get_numeric("cmd_timeout", 120)
    install_path = params["install_winfsp_path"]
    check_installed_cmd = params.get("check_winfsp_installed_cmd",
                                     r'dir "%s" |findstr /I winfsp')
    check_installed_cmd = check_installed_cmd % install_path
    install_winfsp_cmd = r'msiexec /i WIN_UTILS:\winfsp.msi /qn'
    install_cmd = params.get("install_winfsp_cmd",
                             install_winfsp_cmd)
    # install winfsp tool
    test.log.info("Install winfsp for windows guest.")
    installed = session.cmd_status(check_installed_cmd) == 0
    if installed:
        test.log.info("Winfsp tool is already installed.")
    else:
        install_cmd = utils_misc.set_winutils_letter(session, install_cmd)
        session.cmd(install_cmd, cmd_timeout)
        if not utils_misc.wait_for(lambda: not session.cmd_status(
                check_installed_cmd), 60):
            test.error("Winfsp tool is not installed.")


def get_virtiofs_driver_letter(test, fs_target, session):
    """
    Get the virtiofs driver letter( Windows guest only )
    :param test: QEMU test object
    :param fs_target: virtio fs target
    :param session: the session of guest
    :return driver_letter: the driver letter of the virtiofs
    """
    test.log.info("Get driver letter of virtio fs target, the driver label is "
                  "%s." % fs_target)
    vol_con = "VolumeName='%s'" % fs_target
    driver_letter = utils_misc.wait_for(
        lambda: utils_misc.get_win_disk_vol(session, condition=vol_con),
        timeout=120)
    if driver_letter is None:
        test.fail("Could not get virtio-fs mounted driver letter.")
    return driver_letter


def viofs_basic_io_test(test, params, vm):
    """
    Basic io test in Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: the vm object
    """
    error_context.context("Running viofs basic io test", LOG_JOB.info)
    session = vm.wait_for_login()
    test_file = params.get('test_file', "virtio_fs_test_file")
    cmd_dd = params.get("cmd_dd", 'dd if=/dev/random of=%s bs=1M count=200')
    io_timeout = params.get("timeout", 120)
    cmd_md5 = params.get("cmd_md5", '%s: && md5sum.exe %s')
    fs_source = params.get("fs_source_dir")
    base_dir = params.get("fs_source_base_dir",
                          data_dir.get_data_dir())
    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)

    host_data = os.path.join(fs_source, test_file)

    fs_target = params.get("fs_target")
    driver_letter = get_virtiofs_driver_letter(test, fs_target, session)
    fs_dest = "%s:" % driver_letter
    guest_file = os.path.join(fs_dest, test_file)

    test.log.info("Creating file under %s inside guest." % fs_dest)
    session.cmd(cmd_dd % guest_file, io_timeout)

    guest_file_win = guest_file.replace("/", "\\")
    cmd_md5_vm = cmd_md5 % (driver_letter, guest_file_win)
    md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]

    test.log.info("md5 of the guest file: " + md5_guest)
    md5_host = process.run("md5sum %s" % host_data,
                           io_timeout).stdout_text.strip().split()[0]
    test.log.info("md5 of the host file: " + md5_host)
    if md5_guest != md5_host:
        test.fail('The md5 value of host is not same to guest.')
    else:
        test.log.info("The md5 of host is as same as md5 of guest.")
