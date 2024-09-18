import logging
import os
import random
import re
import time

from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_net

from provider import virtio_fs_utils, win_driver_utils
from provider.storage_benchmark import generate_instance
from qemu.tests.virtio_serial_file_transfer import transfer_data

LOG_JOB = logging.getLogger("avocado.test")


driver_name_list = [
    "balloon",
    "viostor",
    "vioscsi",
    "viorng",
    "viofs",
    "vioser",
    "pvpanic",
    "netkvm",
    "vioinput",
    "fwcfg",
]

device_hwid_list = [
    '"PCI\\VEN_1AF4&DEV_1002" "PCI\\VEN_1AF4&DEV_1045"',
    '"PCI\\VEN_1AF4&DEV_1001" "PCI\\VEN_1AF4&DEV_1042"',
    '"PCI\\VEN_1AF4&DEV_1004" "PCI\\VEN_1AF4&DEV_1048"',
    '"PCI\\VEN_1AF4&DEV_1005" "PCI\\VEN_1AF4&DEV_1044"',
    '"PCI\\VEN_1AF4&DEV_105A"',
    '"PCI\\VEN_1AF4&DEV_1003" "PCI\\VEN_1AF4&DEV_1043"',
    '"ACPI\\QEMU0001"',
    '"PCI\\VEN_1AF4&DEV_1000" "PCI\\VEN_1AF4&DEV_1041"',
    '"PCI\\VEN_1AF4&DEV_1052"',
    '"ACPI\\VEN_QEMU&DEV_0002"',
]

device_name_list = [
    "VirtIO Balloon Driver",
    "Red Hat VirtIO SCSI controller",
    "Red Hat VirtIO SCSI pass-through controller",
    "VirtIO RNG Device",
    "VirtIO FS Device",
    "VirtIO Serial Driver",
    "QEMU PVPanic Device",
    "Red Hat VirtIO Ethernet Adapter",
    "VirtIO Input Driver",
    "QEMU FwCfg Device",
]


def install_gagent(session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd):
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
        test.fail(
            "qemu-guest-agent install failed," " the detailed info:\n%s." % o_inst
        )
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
    for driver_name, device_name, device_hwid in zip(
        driver_name_list, device_name_list, device_hwid_list
    ):
        win_driver_utils.uninstall_driver(
            session, test, devcon_path, driver_name, device_name, device_hwid
        )


@error_context.context_aware
def run_installer_with_interaction(
    vm, session, test, params, run_installer_cmd, copy_files_params=None
):
    """
    Install/uninstall/repair virtio-win drivers and qxl,spice and
    qemu-ga-win by installer.

    :param vm: vm object
    :param session: The guest session object.
    :param test: kvm test object.
    :param params: the dict used for parameters
    :param run_installer_cmd: install/uninstall/repair cmd cmd.
    :param copy_files_params: copy files params.
    :return session: a new session after restart of installer
    """
    error_context.context(
        "Run virtio-win-guest-tools.exe by %s." % run_installer_cmd, LOG_JOB.info
    )
    vm.send_key("meta_l-d")
    time.sleep(30)
    if copy_files_params:
        win_driver_utils.copy_file_to_samepath(session, test, copy_files_params)
    session = win_driver_utils.run_installer(
        vm, session, test, params, run_installer_cmd
    )
    return session


@error_context.context_aware
def win_installer_test(session, test, params):
    """
    Windows installer related check.

    :param session: The guest session object.
    :param test: kvm test object
    :param params: the dict used for parameters.
    """
    error_context.context(
        "Check if virtio-win-guest-too.exe " "is signed by redhat", LOG_JOB.info
    )
    status = session.cmd_status(params["signed_check_cmd"])
    if status != 0:
        test.fail("Installer not signed by redhat.")


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
    if params.get("driver_name"):
        driver_name_list = [params["driver_name"]]
        device_name_list = [params["device_name"]]
    for driver_name, device_name in zip(driver_name_list, device_name_list):
        error_context.context("%s Driver Check" % driver_name, LOG_JOB.info)
        inf_path = win_driver_utils.get_driver_inf_path(
            session, test, media_type, driver_name
        )
        expected_ver = session.cmd(
            "type %s | findstr /i /r DriverVer.*=" % inf_path, timeout=360
        )
        expected_ver = expected_ver.strip().split(",", 1)[-1]
        if not expected_ver:
            test.error("Failed to find driver version from inf file")
        LOG_JOB.info("Target version is '%s'", expected_ver)
        ver_list = win_driver_utils._pnpdrv_info(
            session, device_name, ["DriverVersion"]
        )
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
def check_gagent_version(session, test, gagent_pkg_info_cmd, expected_gagent_version):
    """
    Check whether guest agent version is right.

    :param session: The guest session object.
    :param test: kvm test object
    :param gagent_pkg_info_cmd: guest-agent pkg info check command.
    :param expected_gagent_version: expected gagent version.
    """
    error_context.context("Check if gagent version is correct.", LOG_JOB.info)
    actual_gagent_version = session.cmd_output(gagent_pkg_info_cmd).split()[-2]
    if actual_gagent_version != expected_gagent_version:
        test.fail(
            "gagent version is not right, expected is %s but got %s"
            % (expected_gagent_version, actual_gagent_version)
        )


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
        session, disk_index[0], img_size
    )
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
    read_rng_cmd = params["read_rng_cmd"]
    read_rng_cmd = utils_misc.set_winutils_letter(session, read_rng_cmd)
    error_context.context("Read virtio-rng device to get random number", LOG_JOB.info)
    output = session.cmd_output(read_rng_cmd)
    if len(re.findall(r"0x\w", output, re.M)) < 2:
        test.fail("Unable to read random numbers " "from guest: %s" % output)


@error_context.context_aware
def iozone_test(test, params, vm, images):
    """
    Run iozone inside guest.

    :param test: kvm test object.
    :param params: the dict used for parameters.
    :param vm: vm object.
    :param img_size: image size.
    """
    iozone = generate_instance(params, vm, "iozone")

    for img in images.split():
        drive_letter = get_drive_letter(test, vm, params["image_size_%s" % img])
        try:
            error_context.context("Running IOzone command on guest", LOG_JOB.info)
            iozone.run(params["iozone_cmd_opitons"] % drive_letter)
        finally:
            iozone.clean()


def viofs_basic_io_test(test, params, vm):
    """
    Basic io test in Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: the vm object
    """
    session = vm.wait_for_login()
    virtio_fs_utils.basic_io_test(test, params, session)
    session.close()


def balloon_test(test, params, vm, balloon_test_win):
    """
    Balloon service test in Windows guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: The vm object
    :param balloon_test_win: Basic functions for memory ballooning testcase
    """
    error_context.context("Running balloon service test...", LOG_JOB.info)
    mem_check = params.get("mem_check", "yes")

    session = vm.wait_for_login()
    error_context.context("Config balloon service in guest", test.log.info)
    balloon_test_win.configure_balloon_service(session)

    tag = "evict"
    min_sz, max_sz = balloon_test_win.get_memory_boundary(tag)
    error_context.context("Running %s test" % tag, test.log.info)
    expect_mem = int(random.uniform(min_sz, max_sz))
    balloon_test_win.run_ballooning_test(expect_mem, tag)

    if mem_check == "yes":
        check_list = params["mem_stat_check_list"].split()
        for mem_check_name in check_list:
            balloon_test_win.memory_stats_check(mem_check_name, True)

    error_context.context("Reset balloon memory...", test.log.info)
    balloon_test_win.reset_memory()
    error_context.context("Reset balloon memory...done", test.log.info)
    session.close()
    error_context.context("Balloon test done.", test.log.info)


def pvpanic_test(test, params, vm):
    """
    pvpanic driver function test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: The vm object
    """
    session = vm.wait_for_login()
    # modify the register for windows
    set_panic_cmd = params.get("set_panic_cmd")
    status, output = session.cmd_status_output(set_panic_cmd)
    if status:
        test.error(
            "Command '%s' failed, status: %s, output: %s"
            % (set_panic_cmd, status, output)
        )
    session = vm.reboot(session)

    # triger a crash in guest
    vm.monitor.nmi()

    # check qmp event
    expect_event = params.get("expect_event")
    if not utils_misc.wait_for(lambda: vm.monitor.get_event(expect_event), 60):
        test.fail("Not found expect event: %s" % expect_event)


@error_context.context_aware
def vioser_test(test, params, vm):
    """
    Transfer data file between guest and host, and check result via output;
    Generate random file first if not provided

    :param test: kvm test object
    :param params: dictionary with the test parameters
    :param vm: vm object
    """

    error_context.context("Transfer data between host and guest", test.log.info)
    result = transfer_data(params, vm, sender="both")
    if result is not True:
        test.fail("Test failed. %s" % result[1])


def netkvm_test(test, params, vm):
    """
    nic driver basic test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: The vm object
    """
    get_host_ip_cmd = params["get_host_ip_cmd"]
    session = vm.wait_for_login()

    host_ip = process.system_output(get_host_ip_cmd, shell=True).decode()
    test.log.info("Ping host from guest.")
    utils_net.ping(host_ip, session=session, timeout=20)


@error_context.context_aware
def fwcfg_test(test, params, vm):
    """
    Check if the Memory.dmp file can be saved.

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param vm: VM object.
    """
    tmp_dir = params["tmp_dir"]
    if not os.path.isdir(tmp_dir):
        process.system("mkdir %s" % tmp_dir)
    dump_name = utils_misc.generate_random_string(4) + "Memory.dmp"
    dump_file = tmp_dir + "/" + dump_name

    output = vm.monitor.human_monitor_cmd("dump-guest-memory -w %s" % dump_file)
    if output and "warning" not in output:
        test.fail("Save dump file failed as: %s" % output)
    else:
        cmd = "ls -l %s | awk '{print $5}'" % dump_file
        dump_size = int(process.getoutput(cmd))
        process.system("rm -rf %s" % dump_file, shell=True)
        if dump_size == 0:
            test.fail("The dump file is empty")
