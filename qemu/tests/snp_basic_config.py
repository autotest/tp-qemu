import os

from avocado.utils import process
from virttest import data_dir as virttest_data_dir
from virttest import error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu snp basic test on Milan and above host:
    1. Check host snp capability
    2. Boot snp VM
    3. Verify snp enabled in guest
    4. Check snp qmp cmd and policy

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
    socket_count_cmd = params.get("socket_count_cmd")
    if socket_count_cmd:
        if int(process.getoutput(socket_count_cmd, shell=True)) != 1:
            test.cancel("Host cpu has more than 1 socket, skip the case.")

    vm_name = params["main_vm"]
    vm = env.get_vm(vm_name)
    vm.create()
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    verify_dmesg()
    vm_policy = vm.params.get_numeric("snp_policy")
    guest_check_cmd = params["snp_guest_check"]
    sev_guest_info = vm.monitor.query_sev()
    if sev_guest_info["snp-policy"] != vm_policy:
        test.fail("QMP snp policy doesn't match %s." % vm_policy)
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
