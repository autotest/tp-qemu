import os

from avocado.utils import process
from virttest import env_process, error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Qemu sev basic test on Milan and above host:
    1. Check host sev capability
    2. Generate dhcert and session files
    3. Boot sev VM with dhcert
    4. Verify sev enabled

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start sev test", test.log.info)
    timeout = params.get_numeric("login_timeout", 240)

    sev_module_path = params["sev_module_path"]
    if os.path.exists(sev_module_path):
        f = open(sev_module_path, "r")
        output = f.read().strip()
        f.close()
        if output not in params.objects("module_status"):
            test.cancel("Host sev-es support check fail.")
    else:
        test.cancel("Host sev-es support check fail.")

    sev_tool_pkg = params.get("sev_tool_pkg")
    s, o = process.getstatusoutput("rpm -qa | grep %s" % sev_tool_pkg, shell=True)
    if s != 0:
        install_status = utils_package.package_install(sev_tool_pkg)
        if not install_status:
            test.cancel("Failed to install %s." % sev_tool_pkg)

    vm_name = params["main_vm"]
    files_remove = []
    try:
        process.system_output("sevctl export --full vm.chain", shell=True)
        files_remove.append("vm.chain")
        process.system_output(
            "sevctl session --name " + vm_name + " vm.chain " + params["vm_sev_policy"],
            shell=True,
        )
        session_files = ["godh.b64", "session.b64", "tek.bin", "tik.bin"]
        files_remove.extend([f"{vm_name}_{name}" for name in session_files])
        params["vm_sev_dh_cert_file"] = os.path.abspath("%s_godh.b64" % vm_name)
        params["vm_sev_session_file"] = os.path.abspath("%s_session.b64" % vm_name)
    except Exception as e:
        test.fail("Insert guest dhcert and session blob failed, %s" % str(e))

    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.create()
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    vm.monitor.query_sev_launch_measure()
    try:
        session.cmd_output(params["sev_guest_check"], timeout=240)
    except Exception as e:
        test.fail("Guest sev verify fail: %s" % str(e))
    finally:
        session.close()
        vm.destroy()
        for file in files_remove:
            if os.path.exists(file):
                os.remove(file)
