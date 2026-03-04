import os

from avocado.utils import process
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context

from provider.tdx import TDXDcap, TDXHostCapability


@error_context.context_aware
def run(test, params, env):
    """
    Qemu tdx pccs test:
    1. Setup SGX DCAP packages + pccsadmin tool test
    2. Boot a TDX VM
    3. Verify TDX attestation

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start tdx pccs test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    # Check host TDX capability
    tdx_host_cap = TDXHostCapability(test, params)
    tdx_host_cap.validate_tdx_cap()

    # Setup SGX DCAP packages and pccsadmin tool test
    tdx_dcap = TDXDcap(test, params)
    # Check DCAP preset services first
    dcap_preset_services = params.get("dcap_preset_services", "").split()
    for service in dcap_preset_services:
        if service:
            tdx_dcap.check_preset_service(service)
    dcap_non_preset_services = params.get("dcap_non_preset_services", "").split()
    all_services = dcap_preset_services + dcap_non_preset_services

    # Check DCAP services status before setup; skip config if already active
    if tdx_dcap.verify_dcap_services(all_services, fail_on_inactive=False):
        test.log.info("All DCAP services already active, skip PCCS/QCNL setup")
    else:
        # Setup PCCS and SGX QCNL configuration
        tdx_dcap.setup_pccs_config()
        tdx_dcap.setup_sgx_qcnl_config()

        # Restart DCAP services
        tdx_dcap.restart_dcap_services(all_services)

        # Verify services are started and enabled
        tdx_dcap.verify_dcap_services(all_services)

    # Test pccsadmin tool
    pccsadmin_script = params.get("pccsadmin_script")
    pccs_admin_token = params.get("pccs_admin_token")
    pccs_port = params.get("pccs_port")
    error_context.context("Test pccsadmin tool", test.log.info)
    try:
        deps_dir = virttest_data_dir.get_deps_dir()
        pccsadmin_test_script = os.path.join(deps_dir, pccsadmin_script)
        result = process.run(
            f"bash {pccsadmin_test_script} {pccs_admin_token} {pccs_port}",
            shell=True,
            timeout=300,
        )
        test.log.info("pccsadmin test output: %s", result.stdout_text)
    except Exception as e:
        test.fail("pccsadmin tool test failed: %s" % str(e))

    # Boot TDX VM
    error_context.context("Boot TDX VM", test.log.info)
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.create()
    vm.verify_alive()

    session = None
    try:
        # Verify TDX enabled in guest
        error_context.context("Verify TDX enabled in guest", test.log.info)
        guest_check_cmd = params["tdx_guest_check"]
        session = vm.wait_for_login(timeout=timeout)
        session.cmd_status_output(guest_check_cmd, timeout=240)

        # Verify TDX attestation
        error_context.context("Verify TDX attestation", test.log.info)
        deps_dir = virttest_data_dir.get_deps_dir()
        tdx_dcap = TDXDcap(test, params, vm)
        tdx_dcap.verify_dcap_attestation(session, deps_dir)
    except Exception as e:
        test.fail("Guest tdx verify or attestation failed: %s" % str(e))
    finally:
        if session is not None:
            session.close()
        vm.destroy()
