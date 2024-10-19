import ast

from virttest import error_context

from provider import virtio_fs_utils, win_driver_installer_test, win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Boot guest with the target virtio device.
    2) Install driver via virtio-win-guest-tools.exe.
    3) Run virtio-win-guest-tools.exe signature check command in guest.
    4) Verify the qemu-ga version match expected version.
    5) Run driver signature check command in guest.
       Verify target driver.
    6) Run driver function test.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    devcon_path = params["devcon_path"]
    driver_name = params["driver_name"]
    device_name = params["device_name"]
    device_hwid = params["device_hwid"]

    # gagent version check test config
    qemu_ga_pkg = params["qemu_ga_pkg"]
    gagent_pkg_info_cmd = params["gagent_pkg_info_cmd"]
    gagent_install_cmd = params["gagent_install_cmd"]
    gagent_uninstall_cmd = params["gagent_uninstall_cmd"]

    run_install_cmd = params["run_install_cmd"]
    driver_test_params = params.get("driver_test_params", "{}")
    driver_test_params = ast.literal_eval(driver_test_params)

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    expected_gagent_version = win_driver_installer_test.install_gagent(
        session, test, qemu_ga_pkg, gagent_install_cmd, gagent_pkg_info_cmd
    )
    win_driver_installer_test.uninstall_gagent(session, test, gagent_uninstall_cmd)

    win_driver_utils.uninstall_driver(
        session, test, devcon_path, driver_name, device_name, device_hwid
    )
    session = vm.reboot(session)

    session = win_driver_installer_test.run_installer_with_interaction(
        vm, session, test, params, run_install_cmd, copy_files_params=params
    )
    win_driver_installer_test.win_installer_test(session, test, params)
    win_driver_installer_test.check_gagent_version(
        session, test, gagent_pkg_info_cmd, expected_gagent_version
    )
    win_driver_installer_test.driver_check(session, test, params)

    driver_test_names = params.objects("driver_test_names")
    if "viofs_basic_io" in driver_test_names:
        virtio_fs_utils.run_viofs_service(test, params, session)
    elif "balloon" in driver_test_names:
        balloon_test_win = BallooningTestWin(test, params, env)
        driver_test_params = {"balloon_test_win": balloon_test_win}
    for test_name in driver_test_names:
        test_func = "win_driver_installer_test.%s_test" % test_name
        eval("%s(test, params, vm, **driver_test_params)" % test_func)

    session.close()
