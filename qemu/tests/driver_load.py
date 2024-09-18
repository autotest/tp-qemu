import re
import time

from virttest import error_context, utils_misc, utils_test


@error_context.context_aware
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

    def load_driver(cmd, driver_id):
        """
        Load driver
        :param cmd: Driver load cmd
        :param driver_id: Driver id in windows guest
        """
        nic_index = len(vm.virtnet) - 1
        session = vm.wait_for_login(nic_index=nic_index)
        if params["os_type"] == "windows":
            cmd = cmd.replace("DRIVER_ID", driver_id)

        status, output = session.cmd_status_output(cmd)
        session.close()
        if status != 0:
            test.fail("failed to load driver, %s" % output)

    def unload_driver(cmd, driver_id):
        """
        Unload driver
        :param cmd: Driver unload cmd
        :param driver_id: Driver id in windows guest
        """
        nic_index = len(vm.virtnet) - 1
        session = vm.wait_for_login(nic_index=nic_index)
        if params["os_type"] == "windows":
            cmd = cmd.replace("DRIVER_ID", driver_id)

        status, output = session.cmd_status_output(cmd)
        session.close()
        if status != 0:
            if "reboot" in output:
                vm.reboot()
                session.close()
            else:
                test.fail("failed to unload driver, %s" % output)

    def get_driver_id(cmd, pattern):
        """
        Get driver id from guest
        :param cmd: cmd to get driver info
        :param pattern: pattern to filter driver id
        """
        nic_index = len(vm.virtnet) - 1
        session = vm.wait_for_login(nic_index=nic_index)
        output = session.cmd_output(cmd)
        driver_id = re.findall(pattern, output)
        if not driver_id:
            test.fail("Didn't find driver info from guest %s" % output)

        driver_id = driver_id[0]
        if params["os_type"] == "windows":
            driver_id = "^&".join(driver_id.split("&"))
        session.close()
        return driver_id

    def service_operate(cmd, ignore_error=False):
        """
        Stop/Start service
        :param cmd: cmd to stop/start service
        :param ignore_error: ignore the cmd error while it's True
                             else raise the error
        """
        session = vm.wait_for_login()
        session.cmd(cmd, ignore_all_errors=ignore_error)
        session.close()

    error_context.context("Try to log into guest.", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    stop_service_cmd = params.get("stop_service_cmd")
    start_service_cmd = params.get("start_service_cmd")

    driver_id_pattern = params["driver_id_pattern"]
    driver_id_cmd = utils_misc.set_winutils_letter(session, params["driver_id_cmd"])
    driver_load_cmd = utils_misc.set_winutils_letter(session, params["driver_load_cmd"])
    driver_unload_cmd = utils_misc.set_winutils_letter(
        session, params["driver_unload_cmd"]
    )
    session.close()

    if stop_service_cmd:
        test.log.info("Stop service before driver load testing")
        service_operate(stop_service_cmd)

    try:
        for repeat in range(0, int(params.get("repeats", 1))):
            error_context.context(
                "Unload and load the driver. Round %s" % repeat, test.log.info
            )
            test.log.info("Get driver info from guest")
            driver_id = get_driver_id(driver_id_cmd, driver_id_pattern)

            error_context.context("Unload the driver", test.log.info)
            unload_driver(driver_unload_cmd, driver_id)
            time.sleep(5)
            error_context.context("Load the driver", test.log.info)
            load_driver(driver_load_cmd, driver_id)
            time.sleep(5)
    finally:
        if start_service_cmd:
            test.log.info("Restart service after driver load testing")
            service_operate(start_service_cmd, ignore_error=True)

    test_after_load = params.get("test_after_load")
    if test_after_load:
        utils_test.run_virt_sub_test(test, params, env, sub_type=test_after_load)
