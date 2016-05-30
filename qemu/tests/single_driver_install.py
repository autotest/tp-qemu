import re
import logging

from virttest import utils_misc
from virttest import error_context
from aexpect import ShellCmdError


@error_context.context_aware
def run(test, params, env):
    """
    This Test is mainly used as subtests
    1) Boot up VM
    2) Uninstall driver (Optional)
    3) Reboot vm (Based on step 2)
    4) Update / Downgrade / Install driver
    5) Reboot vm
    6) Backup driver installation logs

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def show_file_extentions(session):
        """
        Show file extentions in windows guest.

        :param session: VM session.
        """
        show_file_ext_cmd = params.get("show_file_ext_cmd")
        session.cmd(show_file_ext_cmd)

    def get_installation_logs(session):
        """
        Get driver installation log.

        :param session: VM session.
        """
        tmp_debug = r"C:\Windows\DPINST.log, C:\driver_install.log"
        driver_logs = params.get("driver_debug_file", tmp_debug).split(',')
        for _file in driver_logs:
            status = session.cmd_status("dir %s" % _file)
            if not status:
                output = session.cmd("type %s" % _file)
                _file_host = re.split(r'\\', '%r' % _file)[-1]
                _debug_log = open("%s/%s" % (test.resultsdir, _file_host), "w")
                _debug_log.write("%s\n" % output)
                _debug_log.close()

    def reboot(vm, session=None):
        """
        Reboot guest.

        :param vm: VM onject.
        :param session: VM session.
        """
        nic_idx = len(vm.virtnet) - 1
        while nic_idx >= 0:
            try:
                return vm.reboot(nic_index=nic_idx)
            except Exception:
                nic_idx -= 1
                if nic_idx < 0:
                    raise
                logging.warn("Unable to login guest, "
                             "try to login via nic %d" % nic_idx)

    def get_driver_path(session, driver_name):
        """
        Get the driver path which would be installed.

        :param session: VM session.
        :param driver_name: Driver name.

        :return driver_path: Return the driver path.
        """
        guest_name = params["guest_name"]
        alias_map = params.get("guest_alias")
        vol_virtio_key = "VolumeName like '%virtio-win%'"
        vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
        logging.debug("vol_virtio is %s" % vol_virtio)

        if alias_map:
            guest_list = dict([x.split(":") for x in alias_map.split(",")])
            guest_name = guest_list[guest_name]

        # For driver virtio serial, the path name is not same as driver name,
        # need udpate the path here.
        if driver_name == "vioser":
            driver_name = "vioserial"
        driver_path = r"%s:\%s\%s" % (vol_virtio, driver_name, guest_name)
        logging.debug("The driver which would be installed is %s" % driver_path)

        return driver_path

    def install_driver(session, operation):
        """
        Install / Uninstall / Query driver.

        :param session: VM session.
        :param operation: Install / Uninstall / Query driver.
        """
        driver_name = params["driver_name"]
        device_name = params["device_name"]
        driver_path = get_driver_path(session, driver_name)
        driver_install_cmd = params["driver_install_cmd"]
        driver_name = r"--driver_name %s" % driver_name
        device_name = "--device_name \"%s\"" % device_name
        operation = r"--%s" % operation
        vol_utils = utils_misc.get_winutils_vol(session)
        driver_install_cmd = re.sub("WIN_UTILS", vol_utils, driver_install_cmd)
        vol_utils = r"--vol_utils %s:" % vol_utils

        driver_path = r"--driver_path %s" % driver_path
        driver_install_cmd = driver_install_cmd % (operation, driver_path,
                                                   driver_name, device_name,
                                                   vol_utils)

        install_timeout = int(params.get("driver_install_timeout", 600))
        session.cmd(driver_install_cmd, timeout=install_timeout)

    error_context.context("Boot up guest with setup parameters", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    try:
        error_context.context("Show file extentions", logging.info)
        show_file_extentions(session)
        session = reboot(vm, session)

        uninstall_flag = params.get("need_uninstall", "no")
        if uninstall_flag == "yes":
            operation = "uninstall_driver"
            error_context.context("Uninstall driver", logging.info)
            install_driver(session, operation)
            session = reboot(vm, session)

        operation = "install_driver"
        error_context.context("Install driver", logging.info)
        install_driver(session, operation)
        session = reboot(vm, session)

        if uninstall_flag == "no":
            operation = "verify_driver"
            error_context.context("Verify driver is same as expected", logging.info)
            install_driver(session, operation)

    finally:
        if session:
            error_context.context("Get driver installation log", logging.info)
            try:
                get_installation_logs(session)
            except ShellCmdError:
                pass
            session.close()
