from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Save VM while it's running, and then load it again.

    1) Launch a VM.
    2) Save VM via human monitor while VM is running. (unsafe)
    3) Check if it exists in snapshots.
    4) Load VM via human monitor.
    5) Verify kernel and dmesg.
    6) Delete snapshot after testing.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    snapshot_tag = "vm_" + utils_misc.generate_random_string(8)
    os_type = params["os_type"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login().close()
    try:
        error_context.base_context("Saving VM to %s" % snapshot_tag, test.log.info)
        vm.monitor.human_monitor_cmd("savevm %s" % snapshot_tag)
        vm_snapshots = vm.monitor.info("snapshots")
        if snapshot_tag not in vm_snapshots:
            test.fail("Failed to save VM to %s" % snapshot_tag)
        error_context.context("Loading VM from %s" % snapshot_tag, test.log.info)
        vm.monitor.human_monitor_cmd("loadvm %s" % snapshot_tag)
        if os_type == "linux":
            vm.verify_kernel_crash()
            vm.verify_dmesg()
    finally:
        if snapshot_tag in vm.monitor.info("snapshots"):
            vm.monitor.human_monitor_cmd("delvm %s" % snapshot_tag)
