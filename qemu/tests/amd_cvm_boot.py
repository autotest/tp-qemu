import os

from avocado.utils import cpu
from virttest import error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu CVM (SEV/SEV-ES/SEV-SNP) basic test on AMD Milan and above hosts.
    Steps:
    1. Verify host SEV/SEV-ES/SEV-SNP support via
       /sys/module/kvm_amd/parameters.
    2. Check for valid OVMF BIOS path.
    3. Validate host CPU (Milan, Genoa, Turin).
    4. Boot a SEV or SEV-ES or SEV-SNP CVM VM.
    5. Verify CVM enablement in guest via dmesg.
    6. Check QMP query-sev policy and state.
    :param test: QEMU test object.
    :param params: Dictionary with test parameters:
        - cvm_module_path: Path to SEV* status file
            (e.g., /sys/module/kvm_amd/parameters/sev).
        - module_status: Expected SEV*/SEV-SNP status (e.g., ["1", "Y"]).
        - bios_path: Path to OVMF BIOS for CVM.
        - main_vm: Name of the VM to test.
        - vm_secure_guest_type: Type of CVM ("sev" "seves" or "snp").
        - vm_sev_policy: Expected SEV/SEV-ES/SNP policy value.
        - cvm_guest_check: Command to verify CVM ("sev" "seves" or "snp")
          enablement in the guest.
            (e.g., 'journalctl|grep -i -w sev-es').
        - login_timeout: VM login timeout in seconds (default: 240).
    :param env: Dictionary with test environment.
    :raises: test.cancel if host lacks specific cvm capability support,
             BIOS is missing, or CPU is unsupported.
    :raises: test.fail if guest cvm capability verification,
             QMP policy check, or dmesg check fails.

    """
    error_context.context("Start cvm test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    cvm_module_path = params["cvm_module_path"]
    cvm_type = params["vm_secure_guest_type"]
    if os.path.exists(cvm_module_path):
        with open(cvm_module_path) as f:
            output = f.read().strip()
        if output not in params.objects("module_status"):
            test.cancel(f"Host support for {cvm_type} capability check failed.")
    else:
        test.cancel(f"Host support for {cvm_type} capability check failed.")
    biospath = params.get("bios_path")
    if not os.path.isfile(biospath):
        test.cancel("bios_path not exist %s." % biospath)
    family_id = int(cpu.get_family())
    model_id = int(cpu.get_model())
    supported_cpus = {
        "milan": [25, 0, 15],
        "genoa": [25, 16, 31],
        "bergamo": [25, 160, 175],
        "turin": [26, 0, 31],
    }
    host_platform = None
    for platform, values in supported_cpus.items():
        if values[0] == family_id:
            if model_id >= values[1] and model_id <= values[2]:
                host_platform = platform
    if not host_platform:
        test.cancel("Unsupported platform. Requires Milan or above.")
    test.log.info("Detected platform: %s", host_platform)
    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    try:
        vm.create()
        vm.verify_alive()
    except Exception as e:
        test.fail("Failed to create VM: %s", str(e))
    error_context.context("Logging into VM", test.log.info)
    try:
        session = vm.wait_for_login(timeout=timeout)
    except Exception as e:
        test.fail("Failed to login to VM: %s", str(e))
    # Verify host dmesg for any errors during the guest boot
    verify_dmesg()

    cvm_guest_info = vm.monitor.query_sev()
    if not cvm_guest_info:
        test.fail("QMP query-sev returned empty response.")
    test.log.info("QMP cvm info: %s:", cvm_guest_info)
    expected_policy = vm.params.get_numeric("vm_sev_policy")
    if params["vm_secure_guest_type"] == "snp":
        if "snp-policy" not in cvm_guest_info:
            test.fail("QMP snp-policy not found in query-sev response.")
        actual_policy = cvm_guest_info["snp-policy"]
    else:
        if "policy" not in cvm_guest_info:
            test.fail("QMP policy not found in query-sev response.")
        actual_policy = cvm_guest_info["policy"]
    if actual_policy != expected_policy:
        test.fail(
            "QMP cvm policy mismatch: expected %s, got %s",
            expected_policy,
            actual_policy,
        )
    if cvm_guest_info.get("state") != "running":
        test.fail("CVM state is %s, expected 'running'", cvm_guest_info.get("state"))
    error_context.context(
        f"Verifying cvm {cvm_type} capability enablement in guest", test.log.info
    )
    guest_check_cmd = params["cvm_guest_check"]
    try:
        return_code, output = session.cmd_status_output(guest_check_cmd, timeout=240)
        if return_code != 0:
            test.fail(
                "Guest cvm %s capability check failed with return code %d: %s",
                cvm_type,
                return_code,
                output,
            )
        test.log.info("Guest cvm %s capability check output: %s", cvm_type, output)
    except Exception as e:
        test.fail("Guest cvm {cvm_type} capability verify fail: %s" % str(e))
    finally:
        session.close()
        vm.destroy()
