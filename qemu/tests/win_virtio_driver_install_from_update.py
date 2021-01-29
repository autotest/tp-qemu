import logging
import time

from virttest import error_context
from virttest import utils_misc

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Install drivers from windows update:

    1) Boot guest with the device.
    2) Check windows update service is running
       if not, start the service.
    3) Install drivers from windows update.
    4) Run driver signature check command in guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def start_wuauserv_service(session):
        """
        Start wuauserv service.

        :param session: The guest session object.
        """
        wuauserv_status_cmd = params["wuauserv_status_cmd"]
        status = session.cmd_status(wuauserv_status_cmd)
        if status != 0:
            wuauserv_service_cfg_cmd = params["wuauserv_service_cfg_cmd"]
            status = session.cmd_status(wuauserv_service_cfg_cmd)
            if status != 0:
                test.fail("Change wuauserv service config not success")
            wuauserv_start_cmd = params["wuauserv_start_cmd"]
            status = session.cmd_status(wuauserv_start_cmd)
            if status != 0:
                test.fail("Fail to start wuauserv service")

    driver_name = params["driver_name"]
    device_name = params["device_name"]
    device_hwid = params["device_hwid"]
    devcon_path = params["devcon_path"]
    install_driver_cmd = params["install_driver_cmd"]
    check_stat = params["check_driver_stat"] % driver_name
    chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
    chk_timeout = int(params.get("chk_timeout", 240))

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    error_context.context("Start wuauserv service", logging.info)
    start_wuauserv_service(session)

    error_context.context("Uninstall %s driver" % driver_name, logging.info)
    win_driver_utils.uninstall_driver(session, test, devcon_path, driver_name,
                                      device_name, device_hwid)
    session = vm.reboot(session)

    error_context.context("Install drivers from windows update", logging.info)
    install_driver_cmd = utils_misc.set_winutils_letter(session,
                                                        install_driver_cmd)
    vm.send_key('meta_l-d')
    time.sleep(30)
    session.cmd(install_driver_cmd)
    # workaround for viostor and vioscsi as driver status still be running
    # after uninstall
    if driver_name in ('viostor', 'vioscsi'):
        time.sleep(120)
    if not utils_misc.wait_for(lambda: not session.cmd_status(check_stat),
                               600, 0, 10):
        test.fail("%s Driver can not be installed correctly from "
                  "windows update" % driver_name)

    error_context.context("%s Driver Check" % driver_name, logging.info)
    session = vm.reboot(session)

    chk_output = session.cmd_output(chk_cmd, timeout=chk_timeout)
    if "FALSE" in chk_output:
        fail_log = "VirtIO driver is not digitally signed!"
        fail_log += " VirtIO driver check output: '%s'" % chk_output
        test.fail(fail_log)
    elif "TRUE" not in chk_output:
        test.error("Device %s is not found in guest" % device_name)

    session.close()
