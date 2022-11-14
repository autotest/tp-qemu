import ast

from virttest import error_context
from virttest import utils_misc
from virttest import data_dir

from qemu.tests.balloon_check import BallooningTestWin

from provider import win_driver_utils
from provider import win_driver_installer_test


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Create shared directories on the host.
    2) Run virtiofsd daemons on the host.
    3) Boot guest with all virtio device.
    4) Delete the virtio fs service on guest.
    5) Install driver from previous virtio-win.iso.
       Or virtio-win-guest-tool.
    6) Start virtio fs service on guest.
    7) Upgrade driver via virtio-win-guest-tools.exe
    8) Start virtio fs service on guest.
    9) Verify the qemu-ga version match expected version.
    10) Run driver signature check command in guest.
       Verify target driver.
    11) Run driver function test after virtio-win-guest-tools.exe update.

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
        test.log.info("Changing virtio iso image to '%s'", virtio_iso)
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

    expected_gagent_version = win_driver_installer_test.install_gagent(
                                             session, test,
                                             qemu_ga_pkg,
                                             gagent_install_cmd,
                                             gagent_pkg_info_cmd)

    win_driver_installer_test.uninstall_gagent(session, test,
                                               gagent_uninstall_cmd)

    error_context.context("Delete the viofs service at guest...")
    win_driver_installer_test.delete_viofs_serivce(test, params, session)

    win_driver_installer_test.win_uninstall_all_drivers(session,
                                                        test, params)
    change_virtio_media(params["cdrom_virtio_downgrade"])

    session = vm.reboot(session)

    if params.get("update_from_previous_installer", "no") == "yes":
        error_context.context("install drivers from previous installer",
                              test.log.info)
        win_driver_installer_test.install_test_with_screen_on_desktop(
                                            vm, session, test,
                                            run_install_cmd,
                                            installer_pkg_check_cmd,
                                            copy_files_params=params)
    else:
        for driver_name, device_name, device_hwid in zip(
                    win_driver_installer_test.driver_name_list,
                    win_driver_installer_test.device_name_list,
                    win_driver_installer_test.device_hwid_list):
            win_driver_utils.install_driver_by_virtio_media(session, test,
                                                            devcon_path,
                                                            media_type,
                                                            driver_name,
                                                            device_hwid)
        win_driver_installer_test.install_gagent(session, test, qemu_ga_pkg,
                                                 gagent_install_cmd,
                                                 gagent_pkg_info_cmd)

    error_context.context("Run viofs service...")
    win_driver_installer_test.run_viofs_service(test, params, session)

    error_context.context("Upgrade virtio driver to original",
                          test.log.info)
    change_virtio_media(params["cdrom_virtio"])
    win_driver_installer_test.install_test_with_screen_on_desktop(
                                        vm, session, test,
                                        run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=params)

    error_context.context("Run viofs service after upgrade...")
    win_driver_installer_test.run_viofs_service(test, params, session)

    if params.get("need_reboot", "no") == "yes":
        session = vm.reboot(session)

    win_driver_installer_test.check_gagent_version(session, test,
                                                   gagent_pkg_info_cmd,
                                                   expected_gagent_version)
    win_driver_installer_test.driver_check(session, test, params)

    balloon_test_win = BallooningTestWin(test, params, env)

    error_context.context("Run driver function test after update",
                          test.log.info)
    fail_tests = []
    test_drivers = params.get('test_drivers',
                              win_driver_installer_test.driver_name_list)
    if params.get('test_drivers'):
        test_drivers = params["test_drivers"].split()
    for driver_name in test_drivers:
        test_name = params.get('driver_test_name_%s' % driver_name)
        test_func = "win_driver_installer_test.%s_test" % test_name
        driver_test_params = params.get('driver_test_params_%s'
                                        % driver_name, '{}')
        if driver_name == "balloon":
            driver_test_params = {"balloon_test_win": balloon_test_win}
        else:
            driver_test_params = ast.literal_eval(driver_test_params)
        try:
            eval("%s(test, params, vm, **driver_test_params)" % test_func)
        except Exception as e:
            fail_tests.append('%s:\n%s' % (test_name, str(e)))
    if fail_tests:
        test.fail("Function test failed list is %s after update"
                  % fail_tests)

    session.close()
