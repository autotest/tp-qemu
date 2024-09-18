from virttest import error_context
from virttest.utils_misc import verify_dmesg

from provider.sgx import SGXChecker, SGXHostCapability


@error_context.context_aware
def run(test, params, env):
    """
    Qemu sgx basic test:
    1. Check host sgx capability
    2. Boot sgx VM
    3. Verify sgx enabled in guest
    4. Check sgx qmp cmd
    5. Verify qmp cmd in host and guest sgx capability

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start sgx test", test.log.info)
    timeout = float(params.get("login_timeout", 240))

    sgx_cap = SGXHostCapability(test, params)
    sgx_cap.validate_sgx_cap()
    host_total_epc_size = sgx_cap.host_epc_size
    if params.get("monitor_expect_nodes"):
        sgx_cap.validate_numa_node_count()

    vm = env.get_vm(params["main_vm"])
    vm.create()
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    verify_dmesg()
    dmesg_output = session.cmd_output(params["guest_sgx_check"], timeout=240).strip()
    session.close()

    test_check = SGXChecker(test, params, vm)
    test_check.verify_guest_epc_size(dmesg_output)
    test_check.verify_qmp_host_sgx_cap(host_total_epc_size)
    test_check.verify_qmp_guest_sgx_cap()
    vm.destroy()
