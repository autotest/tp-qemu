import time
import re

from virttest import error_context
from virttest import utils_misc

from provider.win_driver_installer_test import (install_gagent,
                                                uninstall_gagent,
                                                win_uninstall_all_drivers,
                                                win_installer_test,
                                                check_gagent_version,
                                                driver_check,
                                                run_installer_with_interaction)


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
       one by one.
    8) Run virtio-win-guest-tools.exe uninstall test.
    9) Check all drivers are uninstalled.
    10) Run gagent status check command in guest.

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

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    expected_gagent_version = install_gagent(session, test,
                                             qemu_ga_pkg,
                                             gagent_install_cmd,
                                             gagent_pkg_info_cmd)
    uninstall_gagent(session, test, gagent_uninstall_cmd)

    win_uninstall_all_drivers(session, test, params)
    session = vm.reboot(session)

    session = run_installer_with_interaction(vm, session, test, params,
                                             run_install_cmd,
                                             copy_files_params=params)

    win_installer_test(session, test, params)
    check_gagent_version(session, test, gagent_pkg_info_cmd,
                         expected_gagent_version)
    driver_check(session, test, params)

    uninstall_method = params.get('uninstall_method', 'installer')
    error_context.context("Run uninstall test via %s" % uninstall_method,
                          test.log.info)
    vm.send_key('meta_l-d')
    time.sleep(30)
    run_uninstall_cmd = utils_misc.set_winutils_letter(session,
                                                       params["run_uninstall_cmd"])

    session = run_installer_with_interaction(vm, session, test, params,
                                             run_uninstall_cmd)

    if uninstall_method == "msi":
        check_warning_file = params["check_warning_file"]
        output = session.cmd_output(check_warning_file)
        if params["warning_message"] not in output:
            test.fail("Not found expected warning message, the output is %s" % output)
    else:
        s_check, o_check = session.cmd_status_output(installer_pkg_check_cmd)
        if s_check == 0:
            test.fail("Could not uninstall Virtio-win-guest-tools package "
                      "in guest', detail: '%s'" % o_check)

        error_context.context("Check if all drivers are uninstalled.",
                              test.log.info)
        uninstalled_device = []
        device_name_list = ['VirtIO RNG Device', 'VirtIO Serial Driver',
                            'VirtIO Balloon Driver', 'QEMU PVPanic Device',
                            'VirtIO Input Driver',
                            'Red Hat VirtIO Ethernet Adapter',
                            'VirtIO FS Device', 'QEMU FwCfg Device']
        # viostor and vioscsi drivers can not uninstalled by installer
        for device_name in device_name_list:
            chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
            output = session.cmd_output(chk_cmd).strip()
            inf_name = re.findall(r"\.inf", output, re.I)
            if inf_name:
                uninstalled_device.append(device_name)
        if uninstalled_device:
            test.fail("%s uninstall failed" % uninstalled_device)

        error_context.context("Check qemu-ga service.", test.log.info)
        gagent_status_cmd = 'sc query qemu-ga |findstr "RUNNING" '
        status = session.cmd_status(gagent_status_cmd)
        if status == 0:
            test.fail("qemu-ga service still running after uninstall")

    session.close()
