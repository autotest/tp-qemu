import os

from virttest import data_dir as virttest_data_dir
from virttest import env_process, error_context
from virttest.utils_misc import get_mem_info, normalize_data_size, verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu snp basic test on Milan and above host:
    1. Check host snp capability
    2. Adjust guest memory by host resources
    3. Boot snp VM
    4. Verify snp enabled in guest
    5. Test attestation

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    error_context.context("Start sev-snp test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

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
    for vm_name in vms:
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.create()
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        verify_dmesg()
        guest_check_cmd = params["snp_guest_check"]
        try:
            session.cmd_output(guest_check_cmd, timeout=240)
        except Exception as e:
            test.fail("Guest snp verify fail: %s" % str(e))
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
            s = session.cmd_status(guest_cmd, timeout=360)
            if s:
                test.fail("Guest script error")
        finally:
            session.close()
            vm.destroy()
