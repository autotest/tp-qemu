from virttest import env_process, error_context
from virttest.utils_misc import verify_dmesg

from provider.sgx import SGXChecker, SGXHostCapability


@error_context.context_aware
def run(test, params, env):
    """
    Qemu sgx multi vms boot test:
    1. Check host sgx capability
    2. Boot multi sgx VMs
    3. Verify each VM sgx enabled in guest
    4. Check each VM sgx qmp cmd

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Boot four guests", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    sgx_cap = SGXHostCapability(test, params)
    sgx_cap.validate_sgx_cap()
    host_total_epc_size = sgx_cap.host_epc_size
    if params.get("monitor_expect_nodes"):
        sgx_cap.validate_numa_node_count()

    params["start_vm"] = "yes"
    vms = params.objects("vms")
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        verify_dmesg()
        dmesg_output = session.cmd_output(
            params["guest_sgx_check"], timeout=240
        ).strip()
        session.close()

        test_check = SGXChecker(test, params, vm)
        test_check.verify_guest_epc_size(dmesg_output)
        test_check.verify_qmp_host_sgx_cap(host_total_epc_size)
        test_check.verify_qmp_guest_sgx_cap()
