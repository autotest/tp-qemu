import logging

from virttest import error_context
from virttest import utils_misc
from virttest import data_dir

from provider import win_driver_utils
from provider.win_driver_installer_test import (install_gagent,
                                                uninstall_gagent,
                                                win_uninstall_all_drivers,
                                                check_gagent_version,
                                                driver_check,
                                                driver_name_list,
                                                device_hwid_list,
                                                device_name_list,
                                                install_test_with_screen_on_desktop)


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
        logging.info("Changing virtio iso image to '%s'", virtio_iso)
        vm.change_media("drive_virtio", virtio_iso)

    devcon_path = params["devcon_path"]
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]
    run_install_cmd = params["run_install_cmd"]
    media_type = params["virtio_win_media_type"]

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    expected_gagent_version = install_gagent(session, test,
                                             qemu_ga_pkg,
                                             gagent_install_cmd,
                                             gagent_pkg_info_cmd)

    uninstall_gagent(session, test, gagent_uninstall_cmd)

    if params.get("check_qemufwcfg", "no") == "yes":
        driver_name_list.append('qemufwcfg')

    win_uninstall_all_drivers(session, test, params)
    change_virtio_media(params["cdrom_virtio_downgrade"])

    session = vm.reboot(session)

    if params.get("update_from_previous_installer", "no") == "yes":
        error_context.context("install drivers from previous installer",
                              logging.info)
        install_test_with_screen_on_desktop(vm, session, test,
                                            run_install_cmd,
                                            installer_pkg_check_cmd,
                                            copy_files_params=params)
    else:
        for driver_name, device_name, device_hwid in zip(driver_name_list,
                                                         device_name_list,
                                                         device_hwid_list):
            win_driver_utils.install_driver_by_virtio_media(session, test,
                                                            devcon_path,
                                                            media_type,
                                                            driver_name,
                                                            device_hwid)
        install_gagent(session, test, qemu_ga_pkg, gagent_install_cmd,
                       gagent_pkg_info_cmd)

    error_context.context("Upgrade virtio driver to original",
                          logging.info)
    change_virtio_media(params["cdrom_virtio"])
    install_test_with_screen_on_desktop(vm, session, test,
                                        run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=params)
    # TODO: workaround as Bug 1847856，should be removed when the bz is fixed
    session = vm.reboot(session)

    check_gagent_version(session, test, gagent_pkg_info_cmd,
                         expected_gagent_version)
    driver_check(session, test, params)

    session.close()
