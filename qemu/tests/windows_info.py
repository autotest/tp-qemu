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
    get_os_name_cmd = (
        'powershell -command "Get-CimInstance -ClassName Win32_OperatingSystem'
        ' | Select-Object -ExpandProperty Caption"'
    )
    output = session.cmd(get_os_name_cmd)
    output = output.strip()
    test.log.info("Windows name: %s", output)

    error_context.context("Get driver version information in guest.", test.log.info)
    get_driver_info_cmd = (
        'powershell -command "Get-CimInstance -ClassName Win32_SystemDriver'
        ' | Select-Object DisplayName, PathName"'
    )
    system_drivers = session.cmd(get_driver_info_cmd)
    test.log.debug("Drivers exist in the system:\n %s", system_drivers)
    for i in system_drivers.splitlines():
        if re.findall(drivers_pattern, i, re.I):
            driver_info = i.strip().split()
            driver_name = " ".join(driver_info[:-1])
            get_driver_path_cmd = (
                'powershell -command "Get-CimInstance -ClassName Win32_SystemDriver'
                " | Where-Object {$_.DisplayName -eq '%s'}"
                " | Select-Object PathName"
                ' | Format-List"'
            ) % driver_name
            driver_path = session.cmd(get_driver_path_cmd)
            path = driver_path.strip().split(" : ")[-1]
            path = re.sub(r"\\", "\\\\\\\\", path)
            driver_ver_cmd = (
                'powershell -command "(Get-Item -Path "%s").VersionInfo.FileVersion"'
                % path
            )
            output = session.cmd(driver_ver_cmd)
            msg = "Driver %s" % driver_name
            msg += " version is %s" % output.strip()
            test.log.info(msg)
    session.close()
