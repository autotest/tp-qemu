import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    KVM Windows version collect:
    This case is used to collect windows guest informations using in test.
    1) Get os version related informations
    2) Get driver related informations

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    drivers_keywords = params.get("drivers_keywords", "VirtIO vio").split()
    drivers_pattern = "|".join(drivers_keywords)
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Get OS version and name.", test.log.info)
    output = session.cmd("ver")
    test.log.info("Windows version: %s", output.strip())
    output = session.cmd("wmic os get Name")
    output = output.strip().split()[-1]
    test.log.info("Windows name: %s", output)

    error_context.context("Get driver version information in guest.", test.log.info)
    system_drivers = session.cmd("wmic sysdriver get DisplayName,PathName")
    test.log.debug("Drivers exist in the system:\n %s", system_drivers)
    for i in system_drivers.splitlines():
        if re.findall(drivers_pattern, i, re.I):
            driver_info = i.strip().split()
            driver_name = " ".join(driver_info[:-1])
            path = driver_info[-1]
            path = re.sub(r"\\", "\\\\\\\\", path)
            driver_ver_cmd = "wmic datafile where name="
            driver_ver_cmd += "'%s' get version" % path
            output = session.cmd(driver_ver_cmd)
            msg = "Driver %s" % driver_name
            msg += " version is %s" % output.strip().split()[-1]
            test.log.info(msg)
    session.close()
