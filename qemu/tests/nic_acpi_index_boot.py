import re

from virttest import error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    When "acpi-index=N" is enabled, NIC name should always be "ethN"

    1) Boot up guest with a single nic, add nic option "acpi-index=1"
    2) Remove "biosdevname=0" and "net.ifname=0" from kenrel command line
    3) Reboot guest
    4) Check the nic name, the guest nic name enoN == acpi-index=N

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login(timeout=login_timeout)
    ifname = utils_net.get_linux_ifname(session, vm.get_mac_address())
    pattern = int(re.findall(r"\d+", ifname)[-1])
    nic_name_number = params.get_numeric("nic_name_number")
    if pattern == nic_name_number:
        test.log.info("nic name match")
    else:
        test.fail("nic name doesn't match")
    host_ip = utils_net.get_host_ip_address(params)
    status, output = utils_net.ping(host_ip, 10, timeout=30)
    if status:
        test.fail("%s ping %s unexpected, output %s" % (vm.name, host_ip, output))
    if session:
        session.close()
