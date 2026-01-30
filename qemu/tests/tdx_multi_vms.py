from avocado.utils import process
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.utils_misc import (
    get_mem_info,
    normalize_data_size,
)

from provider.tdx import TDXDcap, TDXHostCapability


@error_context.context_aware
def run(test, params, env):
    """
    Qemu tdx basic test on Intel EMR and above host:
    1. Check host tdx capability
    2. Adjust guest memory by host resources
    3. Boot tdx VM
    4. Verify tdx enabled in guest
    5. Test attestation

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Start tdx test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

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

    # Define maximum guests configurations
    max_vms_cmd = params.get("max_vms_cmd")
    if max_vms_cmd:
        max_vms = int(process.system_output(max_vms_cmd, shell=True))
        for i in range(1, max_vms):
            params["vms"] += " vm_%s" % i
        max_smp = int(process.system_output(params["max_vcpu_cmd"], shell=True))
        params["smp"] = max_smp // max_vms

    # Define vm memory size for multi vcpus scenario
    if params.get_numeric("smp") > 1:
        MemFree = float(
            normalize_data_size("%s KB" % get_mem_info(attr="MemFree"), "M")
        )
        vm_num = len(params.get("vms").split())
        params["mem"] = int(MemFree // (2 * vm_num))

    vms = params.objects("vms")
    vms_queue = []
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vms_queue.append(vm)
        vm.create()

    for vm in vms_queue:
        vm.verify_alive()
        guest_check_cmd = params["tdx_guest_check"]
        session = None
        try:
            session = vm.wait_for_login(timeout=timeout)
            session.cmd_status_output(guest_check_cmd, timeout=240)
        except Exception as e:
            test.fail("Guest tdx verify fail: %s" % str(e))
        else:
            # Verify attestation
            deps_dir = virttest_data_dir.get_deps_dir()
            tdx_dcap = TDXDcap(test, params, vm)
            tdx_dcap.verify_dcap_attestation(session, deps_dir)
        finally:
            session.close()
            vm.destroy()
