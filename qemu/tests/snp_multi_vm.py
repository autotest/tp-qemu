import os

from avocado.utils import cpu
from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.utils_misc import get_mem_info, normalize_data_size, verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu snp concurrent multi-VM test on Milan and above host:
    1. Check host snp capability
    2. Adjust guest memory by host resources
    3. Boot multiple SNP VMs concurrently
    4. Verify snp enabled in all guests concurrently
    5. Test attestation on all VMs

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Start sev-snp test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    family_id = cpu.get_family()
    model_id = cpu.get_model()
    dict_cpu = {"251": "milan", "2517": "genoa", "2617": "turin"}
    key = str(family_id) + str(model_id)
    host_cpu_model = dict_cpu.get(key, "unknown")

    snp_module_path = params["snp_module_path"]
    if os.path.exists(snp_module_path):
        with open(snp_module_path) as f:
            output = f.read().strip()
        if output not in params.objects("module_status"):
            test.cancel("Host sev-snp support check fail.")
    else:
        test.cancel("Host sev-snp support check fail.")
    # Define vm memory size for multi vcpus scenario
    if params.get_numeric("smp") > 1:
        MemFree = float(
            normalize_data_size("%s KB" % get_mem_info(attr="MemFree"), "M")
        )
        vm_num = len(params.get("vms").split())
        params["mem"] = MemFree // (2 * vm_num)

    vms = params.objects("vms")
    vms_queue = []

    # Create all VMs concurrently
    error_context.context("Creating all SNP VMs concurrently", test.log.info)
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vms_queue.append(vm)
        vm.create()
        test.log.info("Created SNP VM: %s", vm_name)

    # Verify and test all VMs concurrently
    error_context.context("Testing all SNP VMs concurrently", test.log.info)
    for vm in vms_queue:
        vm.verify_alive()
        guest_check_cmd = params["snp_guest_check"]
        session = None
        try:
            session = vm.wait_for_login(timeout=timeout)
            verify_dmesg()
            session.cmd_output(guest_check_cmd, timeout=240)
        except Exception as e:
            test.fail("Guest snp verify fail for VM %s: %s" % (vm.name, str(e)))
        else:
            # Verify attestation
            error_context.context("Start to do attestation", test.log.info)
            guest_dir = params["guest_dir"]
            host_script = params["host_script"]
            guest_cmd = params["guest_cmd"]
            deps_dir = virttest_data_dir.get_deps_dir()
            host_file = os.path.join(deps_dir, host_script)
            try:
                vm.copy_files_to(host_file, guest_dir)
                session.cmd_output(params["guest_tool_install"], timeout=240)
                session.cmd_output("chmod 755 %s" % guest_cmd)
            except Exception as e:
                test.fail("Guest test preperation fail: %s" % str(e))
            guest_cmd = guest_cmd + " " + host_cpu_model
            s = session.cmd_status(guest_cmd, timeout=360)
            if s:
                test.fail("Guest script error for VM: %s" % vm.name)
        finally:
            if session:
                session.close()
            vm.destroy()
