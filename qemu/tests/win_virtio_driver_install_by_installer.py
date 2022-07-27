import ast

from virttest import error_context

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
    9) Run driver function test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    run_install_cmd = params["run_install_cmd"]
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]
    driver_test_params = params.get("driver_test_params", "{}")
    driver_test_params = ast.literal_eval(driver_test_params)

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    expected_gagent_version = win_driver_installer_test.install_gagent(
        session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd)
    win_driver_installer_test.uninstall_gagent(
            session, test, gagent_uninstall_cmd)
    win_driver_installer_test.win_uninstall_all_drivers(session,
                                                        test,
                                                        params)
    session = vm.reboot(session)
    win_driver_installer_test.install_test_with_screen_on_desktop(
            vm, session, test, run_install_cmd, installer_pkg_check_cmd,
            copy_files_params=params)
    win_driver_installer_test.win_installer_test(session, test, params)
    win_driver_installer_test.check_gagent_version(
            session, test, gagent_pkg_info_cmd, expected_gagent_version)
    win_driver_installer_test.driver_check(session, test, params)

    driver_test_names = params.objects("driver_test_names")
    for test_name in driver_test_names:
        test_func = "win_driver_installer_test.%s_test" % test_name
        eval("%s(test, params, vm, **driver_test_params)" % test_func)

    session.close()
