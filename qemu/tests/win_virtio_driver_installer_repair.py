import ast
import time

from virttest import error_context
from virttest import utils_misc

from provider import win_driver_utils
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
    6) Verify the qemu-ga version match expected version.
    7) Run driver signature check command in guest.
       Verify target driver.
    8) Run virtio-win-guest-tools.exe repair test by uninstall
       the target driver.
    9) Run the driver function test after virtio-win-guest-tools.exe repair.
    10) Repeat step 9 and 10 for other drivers.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    devcon_path = params["devcon_path"]
    run_install_cmd = params["run_install_cmd"]
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]

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
    win_driver_installer_test.win_uninstall_all_drivers(session,
                                                        test, params)
    session = vm.reboot(session)
    win_driver_installer_test.install_test_with_screen_on_desktop(
                                        vm, session, test,
                                        run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=params)
    win_driver_installer_test.win_installer_test(session, test, params)
    win_driver_installer_test.check_gagent_version(session, test,
                                                   gagent_pkg_info_cmd,
                                                   expected_gagent_version)
    win_driver_installer_test.driver_check(session, test, params)

    error_context.context("Run virtio-win-guest-tools.exe repair test",
                          test.log.info)
    unrepaired_driver = []
    fail_tests = []
    for driver_name, device_name, device_hwid in zip(
                win_driver_installer_test.driver_name_list,
                win_driver_installer_test.device_name_list,
                win_driver_installer_test.device_hwid_list):
        error_context.context("Uninstall %s driver"
                              % driver_name, test.log.info)
        win_driver_utils.uninstall_driver(session, test, devcon_path,
                                          driver_name, device_name,
                                          device_hwid)
        session = vm.reboot(session)
        vm.send_key('meta_l-d')
        time.sleep(30)
        run_repair_cmd = utils_misc.set_winutils_letter(
            session, params["run_repair_cmd"])
        session.cmd(run_repair_cmd)
        time.sleep(30)
        error_context.context("Check if %s driver is repaired"
                              % driver_name, test.log.info)
        chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
        status = session.cmd_status(chk_cmd)
        if status != 0:
            test.log.info("%s driver repair failed" % driver_name)
            unrepaired_driver.append(driver_name)
        else:
            error_context.context("Run %s driver function test after repair"
                                  % driver_name, test.log.info)
            test_name = params.get('driver_test_name_%s' % driver_name)
            test_func = "win_driver_installer_test.%s_test" % test_name
            driver_test_params = params.get('driver_test_params_%s'
                                            % driver_name, '{}')
            driver_test_params = ast.literal_eval(driver_test_params)
            if driver_name == "viofs":
                win_driver_installer_test.run_viofs_service(test, params,
                                                            session)
            if driver_name != "balloon":
                driver_test_params = ast.literal_eval(driver_test_params)
            try:
                eval("%s(test, params, vm, **driver_test_params)" % test_func)
            except Exception as e:
                fail_tests.append('%s:\n%s' % (test_name, str(e)))

    if unrepaired_driver or fail_tests:
        test.fail("Repaired failed driver list is %s, repair success but "
                  "function test failed list is %s"
                  % (unrepaired_driver, fail_tests))

    session.close()
