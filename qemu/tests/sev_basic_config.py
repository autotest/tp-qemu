import os

from virttest import error_context
from virttest.utils_misc import verify_dmesg


@error_context.context_aware
def run(test, params, env):
    """
    Qemu sev basic test on Milan and above host:
    1. Check host sev capability
    2. Boot sev VM
    3. Verify sev enabled in guest
    4. Check sev qmp cmd

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

    vms = params.objects("vms")
    for vm_name in vms:
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)
        verify_dmesg()
        vm_policy = vm.params.get_numeric("vm_sev_policy")
        if vm_policy <= 3:
            policy_keyword = "sev"
        else:
            policy_keyword = "sev-es"
        guest_check_cmd = params["sev_guest_check"].format(
            policy_keyword=policy_keyword
        )
        try:
            session.cmd_output(guest_check_cmd, timeout=240)
        except Exception as e:
            test.fail("Guest sev verify fail: %s" % str(e))
        sev_guest_info = vm.monitor.query_sev()
        if sev_guest_info["policy"] != vm_policy:
            test.fail("QMP sev policy doesn't match.")
        else:
            error_context.context("QMP sev policy matches", test.log.info)
        session.close()
