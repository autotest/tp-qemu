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
    output = session.cmd(
        'powershell -command "Get-CimInstance Win32_OperatingSystem'
        ' | Select-Object -ExpandProperty Name"'
    )
    output = output.strip().split()[-1]
    test.log.info("Windows name: %s", output)

    error_context.context("Get driver version information in guest.", test.log.info)
    system_drivers = session.cmd(
        'powershell -command "Get-CimInstance Win32_SystemDriver'
        ' | Format-List DisplayName,PathName"',
        timeout=300,
    )
    test.log.debug("Drivers exist in the system:\n %s", system_drivers)
    for para in re.split(r"(?:\r?\n){2,}", system_drivers.strip()):
        props = {}
        for line in para.splitlines():
            line = line.strip()
            if " : " in line:
                k, v = line.split(" : ", 1)
                props[k.strip()] = v.strip()
        if "DisplayName" not in props or "PathName" not in props:
            continue
        driver_name = props["DisplayName"]
        if not re.findall(drivers_pattern, driver_name, re.I):
            continue
        path = props["PathName"]
        path = re.sub(r"\\", "\\\\\\\\", path)
        driver_ver_cmd = (
            'powershell -command "Get-CimInstance CIM_DataFile'
            " -Filter 'Name=''%s'''"
            ' | Select-Object -ExpandProperty Version"' % path
        )
        output = session.cmd(driver_ver_cmd)
        msg = "Driver %s version is %s" % (driver_name, output.strip())
        test.log.info(msg)
    session.close()
