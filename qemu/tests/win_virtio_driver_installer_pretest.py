import ast
import logging
import re
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_misc, utils_net

from provider import virtio_fs_utils, win_driver_installer_test, win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def run(test, params, env):
    """
    Installer pretest:
    For the pretest, need to install a new image with the lastsinged drivers.

    1) Boot guest with the target installer iso.
    2) Get agent version.
    3) Clear the installed drivers/agent/virtiofs.
    4) Install/update driver via virtio-win-guest-tools.exe.
    5) if creating virtio-win iso
        a. copy driver folder to host
        b. create a virtio-win iso including driver folders
    6) if test installer
        a. Run virtio-win-guest-tools.exe signature check command in guest.
        b. Verify the qemu-ga version match expected version.
        c. Run driver signature check command in guest.
           Verify target driver.
        d) service check.
    7) uninstall test if needed

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def change_virtio_media(cdrom_virtio):
        """
        change iso for virtio-win
        :param cdrom_virtio: iso file
        """
        virtio_iso = utils_misc.get_path(data_dir.get_data_dir(), cdrom_virtio)
        test.log.info("Changing virtio iso image to '%s'", virtio_iso)
        vm.change_media("drive_virtio", virtio_iso)

    def check_network_config(session_serial):
        """
        check ip and dns loss.

        :param session_serial: session_serial
        """
        error_context.context("Network static config check.", test.log.info)
        static_ip_address = utils_net.get_guest_ip_addr(
            session_serial, virtio_nic_mac, os_type="windows"
        )
        LOG_JOB.info("Static ip address is %s", static_ip_address)
        if static_ip_address != params["static_ip"]:
            test.fail("Failed to setup static ip,current ip is %s" % static_ip_address)
        static_dns_address = utils_net.get_windows_nic_attribute(
            session_serial,
            global_switch="nicconfig",
            key="MACAddress",
            value=f"{virtio_nic_mac}",
            target="DNSServerSearchOrder",
        )
        static_dns_address = static_dns_address.strip("{}").strip('"')
        LOG_JOB.info("Static dns address is %s", static_dns_address)
        if static_dns_address != params["static_dns"]:
            test.fail(
                "Static dns is lost after upgrade driver, current dns "
                "is %s" % static_dns_address
            )

    def install_by_pre_installer(session):
        """
        Install installer with previous installer.
        """
        error_context.context("Install drivers from previous installer", test.log.info)
        change_virtio_media(params["cdrom_virtio_downgrade"])
        # add sleep time in case iso changed windows
        # pop up before the installer windows
        time.sleep(2)
        session = win_driver_installer_test.run_installer_with_interaction(
            vm, session, test, params, run_install_cmd, copy_files_params=params
        )
        # set up static ip for network
        session_serial = vm.wait_for_serial_login()
        if vm.virtnet[1].nic_model == "virtio-net-pci":
            ifname = utils_net.get_windows_nic_attribute(
                session_serial, "macaddress", virtio_nic_mac, "netconnectionid"
            )
            setup_ip_cmd = params["setup_ip_cmd"] % ifname
            setup_dns_cmd = params["setup_dns_cmd"] % ifname
            session_serial.cmd_status(setup_ip_cmd)
            session_serial.cmd_status(setup_dns_cmd)
            check_network_config(session_serial)
        session_serial.close()

        # start virtiofs service
        error_context.context("Start viofs service...")
        params["exe_find_cmd"] = (
            'dir /b /s VIOWIN_LTR\\EXE_FILE_NAME |findstr "\\EXE_MID_PATH\\\\"'
        )
        virtio_fs_utils.run_viofs_service(test, params, session)
        params["exe_find_cmd"] = "dir /b /s VIOWIN_LTR\\EXE_FILE_NAME"
        change_virtio_media(params["cdrom_virtio"])
        # sleep a while for the iso ready, in case of blocking installer got start
        time.sleep(10)
        return session

    def driver_uninstall_check():
        """
        Check drivers are all uninstalled
        """
        error_context.context("Check if all drivers are uninstalled.", test.log.info)
        uninstalled_device = []
        device_name_list = win_driver_installer_test.device_name_list

        # Filter out SCSI devices (cannot be uninstalled by installer)
        need_uninstall_devices = [
            name
            for name in device_name_list
            if not any(
                scsi in name for scsi in ["SCSI controller", "SCSI pass-through"]
            )
        ]

        # Filter out VirtIO Viomem Driver if boot_with_viomem is not enabled
        if params.get("boot_with_viomem", "no") == "no":
            need_uninstall_devices = [
                name
                for name in need_uninstall_devices
                if "VirtIO Viomem Driver" not in name
            ]

        if not params.get("vsocks"):
            need_uninstall_devices = [
                name
                for name in need_uninstall_devices
                if "VirtIO VSOCK Device" not in name
            ]

        for device_name in need_uninstall_devices:
            chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
            output = session.cmd_output(chk_cmd).strip()
            LOG_JOB.info("driver is %s, output is %s", device_name, output)
            inf_name = re.findall(r"\.inf", output, re.I)
            if inf_name:
                uninstalled_device.append(device_name)
        if uninstalled_device:
            test.fail("%s uninstall failed" % uninstalled_device)

    def uninstall_by_installer(session):
        """
        Uninstall all msi by installer.
        """
        error_context.context(
            "Run virtio-win-guest-tools.exe uninstall test", test.log.info
        )
        session = win_driver_installer_test.run_installer_with_interaction(
            vm, session, test, params, run_uninstall_cmd
        )
        return session

    def repair_by_installer(session):
        """
        Uninstall virtio-win msi, and then repair by installer
        """
        test.log.info("Remove virtio-win driver by msi.")
        session = win_driver_utils.remove_driver_by_msi(session, vm, params)

        test.log.info("Repair virtio-win driver by installer.")
        session = win_driver_installer_test.run_installer_with_interaction(
            vm, session, test, params, run_repair_cmd
        )
        return session

    def driver_service_check():
        """
        After install the installer, check drivers and services.
        """
        win_driver_installer_test.win_installer_test(session, test, params)
        win_driver_installer_test.check_gagent_version(
            session, test, gagent_pkg_info_cmd, expected_gagent_version
        )
        win_driver_installer_test.driver_check(session, test, params)
        # balloon and virtiofs service check
        fail_tests = []
        for driver_name, device_name, device_hwid in zip(
            win_driver_installer_test.driver_name_list,
            win_driver_installer_test.device_name_list,
            win_driver_installer_test.device_hwid_list,
        ):
            if driver_name == "viofs":
                error_context.context("Check %s service." % driver_name, test.log.info)
                output = virtio_fs_utils.query_viofs_service(test, params, session)
                if not re.search("stopped", output.lower(), re.M):
                    fail_tests.append(driver_name)

            if driver_name == "balloon":
                error_context.context("Check %s service." % driver_name, test.log.info)
                # when initiating balloontestwin class, no need to wait for
                # 180s as the guest os is already booted up for some time.
                params["paused_after_start_vm"] = "yes"
                balloon_test_win = BallooningTestWin(test, params, env)
                output = balloon_test_win.operate_balloon_service(session, "status")
                if not re.search("running", output.lower(), re.M):
                    fail_tests.append(driver_name)
        if fail_tests:
            test.fail(
                "Virtiofs/Balloon service isn't created,"
                "failed driver name is %s" % fail_tests
            )

    def guest_agent_check():
        """
        After uninstall installer, check agent should not be running.
        """
        error_context.context("Check qemu-ga service.", test.log.info)
        gagent_status_cmd = 'sc query qemu-ga |findstr "RUNNING" '
        status = session.cmd_status(gagent_status_cmd)
        if status == 0:
            test.fail("qemu-ga service still running after uninstall")

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    run_install_cmd = params["run_install_cmd"]
    run_repair_cmd = params["run_repair_cmd"]
    run_uninstall_cmd = params["run_uninstall_cmd"]
    driver_test_params = params.get("driver_test_params", "{}")
    driver_test_params = ast.literal_eval(driver_test_params)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()
    virtio_nic_mac = vm.virtnet[1].mac

    # delete virtiofs service
    virtio_fs_utils.delete_viofs_serivce(test, params, session)

    # uninstall the previous drivers
    win_driver_installer_test.win_uninstall_all_drivers(session, test, params)

    if not params.get("create_iso"):
        # get expected agent version
        expected_gagent_version = win_driver_installer_test.install_gagent(
            session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd
        )

        win_driver_installer_test.uninstall_gagent(session, test, gagent_uninstall_cmd)

    session = vm.reboot(session)

    # for update test, install previous installer first.
    if params.get("update_test"):
        session = install_by_pre_installer(session)

    # install/update the current installer
    session = win_driver_installer_test.run_installer_with_interaction(
        vm, session, test, params, run_install_cmd, copy_files_params=params
    )

    if params.get("create_iso"):
        # just create iso, no need to uninstall the installer
        #  as image backup
        guest_path = params.get("guest_path")
        host_installer_path = params.get("host_installer_path")
        mkiso_cmd = params.get("mkiso_cmd")
        vm.copy_files_from(guest_path, host_installer_path)
        process.run(mkiso_cmd)
    else:
        # repair test, uninstall one msi and run installer repair function
        if params.get("repair_test"):
            session = repair_by_installer(session)

        # some check after the installer is installed/update/repaired
        time.sleep(3)
        driver_service_check()
        # for update test, need to check static network
        if params.get("update_test"):
            session_serial = vm.wait_for_serial_login()
            check_network_config(session_serial)
            session_serial.close()

        # uninstall driver test, update testing doesn't need to test it
        if params.get("install_uninstall_test"):
            session = uninstall_by_installer(session)
            # sleep a while for the drivers' uninstallation
            time.sleep(5)
            driver_uninstall_check()
            time.sleep(10)
            guest_agent_check()
