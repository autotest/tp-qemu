from avocado.utils import cpu
from virttest import error_context
from virttest import utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest with iommu_platform, then do ping test

    1) Boot a VM with iommu_platform=on
    2) add intel_iommu=on in guest kernel line
    3) reboot guest
    4) do ping test

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    if cpu.get_vendor() != 'intel':
        test.cancel("This case only support Intel platform")

    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    ping_count = int(params.get("ping_count", 10))
    guest_ip = vm.get_address()

    try:
        status, output = utils_test.ping(guest_ip, ping_count,
                                         timeout=float(ping_count) * 1.5)
        if status != 0:
            test.fail("Ping returns non-zero value %s" % output)
        package_lost = utils_test.get_loss_ratio(output)
        if package_lost != 0:
            test.fail("%s packeage lost when ping guest ip %s " %
                      (package_lost, guest_ip))
    finally:
        session.close()
