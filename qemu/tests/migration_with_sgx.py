from virttest import error_context
from virttest.utils_misc import verify_dmesg

from provider.sgx import SGXChecker, SGXHostCapability


@error_context.context_aware
def run(test, params, env):
    """
    Do migration test with sgx enabled

    1. Check sgx and numa capability
    2. Boot src and dst sgx guests with numa
    3. Migration
    4. Check dst VM sgx enabled in guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    error_context.context("Start sgx test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    sgx_cap = SGXHostCapability(test, params)
    sgx_cap.validate_sgx_cap()
    host_total_epc_size = sgx_cap.host_epc_size
    if params.get("monitor_expect_nodes"):
        sgx_cap.validate_numa_node_count()

    vm = env.get_vm(params["main_vm"])
    vm.create()
    vm.verify_alive()
    vm.wait_for_login(timeout=timeout)

    # do migration
    error_context.context("Start to do sgx vm migration", test.log.info)
    mig_timeout = params.get_numeric("mig_timeout", 3600)
    mig_protocol = params.get("migration_protocol", "tcp")
    vm.migrate(mig_timeout, mig_protocol, env=env)
    session = vm.wait_for_login()
    verify_dmesg()
    dmesg_output = session.cmd_output(params["guest_sgx_check"], timeout=240).strip()
    session.close()

    test_check = SGXChecker(test, params, vm)
    test_check.verify_guest_epc_size(dmesg_output)
    test_check.verify_qmp_host_sgx_cap(host_total_epc_size)
    test_check.verify_qmp_guest_sgx_cap()
    vm.destroy()
