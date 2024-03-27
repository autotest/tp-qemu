import ast
import time

from virttest import error_context
from virttest import utils_misc

from provider import win_driver_utils
from provider import win_driver_installer_test
from provider import virtio_fs_utils

from qemu.tests.balloon_check import BallooningTestWin


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
    run_install_cmd = params["run_install_cmd"]
    installer_pkg_check_cmd = params["installer_pkg_check_cmd"]

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    win_driver_installer_test.win_uninstall_all_drivers(session,
                                                        test, params)
    session = vm.reboot(session)
    win_driver_installer_test.install_test_with_screen_on_desktop(
                                        vm, session, test,
                                        run_install_cmd,
                                        installer_pkg_check_cmd,
                                        copy_files_params=params)

    error_context.context("Run virtio-win-guest-tools.exe repair test",
                          test.log.info)
    test.log.info("Remove virtio-win driver by msi.")
    session = win_driver_utils.remove_driver_by_msi(session, vm, params)

    test.log.info("Repair virtio-win driver by installer.")
    run_repair_cmd = utils_misc.set_winutils_letter(
        session, params["run_repair_cmd"])
    session.cmd(run_repair_cmd)
    time.sleep(30)
    session = vm.reboot(session)

    # driver check after repair
    win_driver_installer_test.driver_check(session, test, params)
    # start viofs test after repair
    virtio_fs_utils.run_viofs_service(test, params, session)

    error_context.context("Run driver function test after repair",
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
            balloon_test_win = BallooningTestWin(test, params, env)
            driver_test_params = {"balloon_test_win": balloon_test_win}
        else:
            driver_test_params = ast.literal_eval(driver_test_params)

        try:
            eval("%s(test, params, vm, **driver_test_params)" % test_func)
        except Exception as e:
            fail_tests.append('%s:\n%s' % (test_name, str(e)))
    if fail_tests:
        test.fail("Function test failed list is %s after repair."
                  % fail_tests)
    session.close()
