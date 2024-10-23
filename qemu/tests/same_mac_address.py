import re
import time

from virttest import error_context, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    boot guest with the same mac address test.

    1) Boot guest with the same mac address
    2) Check if the driver is installed and verified
    3) Check ip of guest
    4) Ping out

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    timeout = int(params.get_numeric("timeout", 360))
    error_context.context(
        "Boot guest with 2 virtio-net with the same mac", test.log.info
    )
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    error_context.context(
        "Check if the driver is installed and " "verified", test.log.info
    )
    driver_verifier = params["driver_verifier"]
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier, timeout
    )
    # wait for getting the 169.254.xx.xx, it gets slower than valid ip.
    time.sleep(60)
    error_context.context("Check the ip of guest", test.log.info)
    mac = vm.virtnet[0].mac
    cmd = 'wmic nicconfig where macaddress="%s" get ipaddress' % mac
    status, output = session.cmd_status_output(cmd, timeout)
    if status:
        test.error("Check ip error, output=%s" % output)
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    test.log.info(lines)

    valid_count = 0
    for l in lines[1:]:
        ip = re.findall(r'(\d+.\d+.\d+.\d+)"', l)[0]
        if not ip.startswith("169.254"):
            valid_count += 1
    if valid_count != 1:
        test.error("%d valid ip found, should be 1" % valid_count)

    error_context.context("Ping out from guest", test.log.info)
    host_ip = utils_net.get_host_ip_address(params)
    status, output = utils_net.ping(host_ip, count=10, timeout=60, session=session)
    if status:
        test.fail("Ping %s failed, output=%s" % (host_ip, output))
