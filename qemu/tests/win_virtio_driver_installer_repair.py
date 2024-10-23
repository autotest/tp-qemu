import ast

from virttest import error_context

from provider import virtio_fs_utils, win_driver_installer_test, win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Acceptance installer test:

    1) Create shared directories on the host.
    2) Run virtiofsd daemons on the host.
    3) Boot guest with all virtio device.
    4) Run driver signature check command in guest.
       Verify target driver.
    5) Uninstall dirvers by msi uninstall.
    6) Run virtio-win-guest-tools.exe repair test.
    7) Run the driver function test after repair.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    run_install_cmd = params["run_install_cmd"]
    run_repair_cmd = params["run_repair_cmd"]

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    win_driver_installer_test.win_uninstall_all_drivers(session, test, params)
    session = vm.reboot(session)

    test.log.info("Install virtio-win driver by installer.")
    session = win_driver_installer_test.run_installer_with_interaction(
        vm, session, test, params, run_install_cmd, copy_files_params=params
    )

    win_driver_installer_test.driver_check(session, test, params)

    error_context.context("Run virtio-win-guest-tools.exe repair test", test.log.info)
    test.log.info("Remove virtio-win driver by msi.")
    session = win_driver_utils.remove_driver_by_msi(session, vm, params)

    test.log.info("Repair virtio-win driver by installer.")
    session = win_driver_installer_test.run_installer_with_interaction(
        vm, session, test, params, run_repair_cmd
    )

    # driver check after repair
    win_driver_installer_test.driver_check(session, test, params)

    error_context.context("Run driver function test after repair", test.log.info)
    fail_tests = []
    test_drivers = params.get(
        "test_drivers", win_driver_installer_test.driver_name_list
    )
    if params.get("test_drivers"):
        test_drivers = params["test_drivers"].split()
    for driver_name in test_drivers:
        test_name = params.get("driver_test_name_%s" % driver_name)
        test_func = "win_driver_installer_test.%s_test" % test_name
        driver_test_params = params.get("driver_test_params_%s" % driver_name, "{}")
        if driver_name == "viofs":
            virtio_fs_utils.run_viofs_service(test, params, session)

        if driver_name == "balloon":
            balloon_test_win = BallooningTestWin(test, params, env)
            driver_test_params = {"balloon_test_win": balloon_test_win}
        else:
            driver_test_params = ast.literal_eval(driver_test_params)

        try:
            eval("%s(test, params, vm, **driver_test_params)" % test_func)
        except Exception as e:
            fail_tests.append("%s:\n%s" % (test_name, str(e)))
    if fail_tests:
        test.fail("Function test failed list is %s after repair." % fail_tests)
    session.close()
