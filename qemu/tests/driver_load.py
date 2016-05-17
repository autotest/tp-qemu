import logging
import re
import time
from autotest.client.shared import error
from virttest import utils_test
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    KVM driver load test:
    1) Log into a guest
    2) Get the driver device id(Windows) or module name(Linux) from guest
    3) Unload/load the device driver
    4) Check if the device still works properly
    5) Repeat step 3-4 several times

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def load_driver(session, cmd, driver_id):
        if params["os_type"] == "windows":
            cmd = cmd.replace("DRIVER_ID", driver_id)

        status, output = session.cmd_status_output(cmd)
        if status != 0:
            raise error.TestFail("failed to load driver, %s" % output)
        if params["os_type"] == "windows":
            if "device(s) are enabled" not in output:
                raise error.TestFail("failed to load driver, %s" % output)

    def unload_driver(session, cmd, driver_id):
        if params["os_type"] == "windows":
            cmd = cmd.replace("DRIVER_ID", driver_id)

        status, output = session.cmd_status_output(cmd)
        if status != 0:
            raise error.TestFail("failed to unload driver, %s" % output)
        if params["os_type"] == "windows":
            if "device(s) disabled" not in output:
                raise error.TestFail("failed to unload driver, %s" % output)

    def check_driver(session, cmd, pattern):
        output = session.cmd_output(cmd)
        driver_id = re.findall(pattern, output)
        if not driver_id:
            raise error.TestFail("Didn't find driver info from guest %s"
                                 % output)

        driver_id = driver_id[0]
        if params["os_type"] == "windows":
            driver_id = '^&'.join(driver_id.split('&'))
        return driver_id

    error.context("Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    # Use the last nic for send driver load/unload command
    nic_index = len(vm.virtnet) - 1
    session = vm.wait_for_login(nic_index=nic_index, timeout=timeout)

    driver_id_cmd = params["driver_id_cmd"]
    driver_id_pattern = params["driver_id_pattern"]
    driver_load_cmd = params["driver_load_cmd"]
    driver_unload_cmd = params["driver_unload_cmd"]

    devcon = params.get("devcon")
    if devcon:
        error.context("Copy devcon.exe from winutils.iso to C:\\")
        copy_devcon_cmd = params.get("devcon") % \
            utils_misc.get_winutils_vol(session)
        session.cmd(copy_devcon_cmd)

    for repeat in range(0, int(params.get("repeats", 1))):
        error.context("Unload and load the driver. Round %s" % repeat,
                      logging.info)
        error.context("Get driver info from guest", logging.info)
        driver_id = check_driver(session, driver_id_cmd, driver_id_pattern)

        error.context("Unload the driver", logging.info)
        unload_driver(session, driver_unload_cmd, driver_id)
        time.sleep(5)

        error.context("Load the driver", logging.info)
        load_driver(session, driver_load_cmd, driver_id)
        time.sleep(5)

    test_after_load = params.get("test_after_load")
    if test_after_load:
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type=test_after_load)
