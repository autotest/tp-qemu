from virttest import error_context

from provider.win_driver_installer_test import (install_gagent,
                                                uninstall_gagent,
                                                win_uninstall_all_drivers,
                                                win_installer_test,
                                                check_gagent_version,
                                                driver_check,
                                                install_test_with_screen_on_desktop)
from provider import win_driver_installer_test


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Create shared directories on the host.
    2) Run virtiofsd daemons on the host.
    3) Boot guest with all virtio device.
    4) Install driver via virtio-win-guest-tools.exe.
    5) Run virtio-win-guest-tools.exe signature check command in guest.
    6) Run QEMU FWCfg Device installed check command in guest.
    7) Verify the qemu-ga version match expected version.
    8) Run driver signature check command in guest.
       Verify target driver.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    run_install_cmd = params["run_install_cmd"]
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]
    register_virtio_fs_service = params.get("register_virtio_fs_service", "")
    basic_io_test = params.get("basic_io_test", "")

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    if register_virtio_fs_service:
        win_driver_installer_test.install_winfsp(test, params, session)
        win_driver_installer_test.viofs_svc_run(test, params, session)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    expected_gagent_version = install_gagent(session, test,
                                             qemu_ga_pkg,
                                             gagent_install_cmd,
                                             gagent_pkg_info_cmd)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    uninstall_gagent(session, test, gagent_uninstall_cmd)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    win_uninstall_all_drivers(session, test, params)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    session = vm.reboot(session)
    install_test_with_screen_on_desktop(vm, session, test, run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=params)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    win_installer_test(session, test, params)
    check_gagent_version(session, test, gagent_pkg_info_cmd,
                         expected_gagent_version)
    driver_check(session, test, params)

    if basic_io_test:
        win_driver_installer_test.basic_io_test(test, params, session)

    session.close()
