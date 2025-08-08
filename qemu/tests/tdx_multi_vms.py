import os

from avocado.utils import process
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.utils_misc import (
    get_mem_info,
    normalize_data_size,
)


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

    tdx_module_path = params["tdx_module_path"]
    if os.path.exists(tdx_module_path):
        with open(tdx_module_path) as f:
            output = f.read().strip()
        if output not in params.objects("module_status"):
            test.cancel("Host tdx support check fail.")
    else:
        test.cancel("Host tdx support check fail.")

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
            session.cmd_output(guest_check_cmd, timeout=240)
        except Exception as e:
            test.fail("Guest tdx verify fail: %s" % str(e))
        else:
            # Verify attestation
            error_context.context("Start to do attestation", test.log.info)
            if not params.get("guest_script"):
                test.cancel("Missing guest_script for attestation.")
            guest_dir = params["guest_dir"]
            host_script = params["host_script"]
            guest_cmd = params["guest_cmd"]
            deps_dir = virttest_data_dir.get_deps_dir()
            host_file = os.path.join(deps_dir, host_script)
            try:
                vm.copy_files_to(host_file, guest_dir)
                session.cmd_output("chmod 755 %s" % guest_cmd)
            except Exception as e:
                test.fail("Guest test preparation fail: %s" % str(e))
            s = session.cmd_status(guest_cmd, timeout=360)
            if s:
                test.fail("Guest script error")
        finally:
            session.close()
            vm.destroy()
