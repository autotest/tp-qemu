from virttest import error_context, utils_test
from virttest.utils_test.qemu import MemoryHotplugTest


@error_context.context_aware
def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Add movable_node to guest kernel line
    3) Hotplug memory to guest and check memory inside guest
    4) Run some stress-ng tests inside guest
    5) Unplug memory from guest and check memory
    6) Repeat step 3) and reboot guest
    8) Repeat step 5)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    utils_test.update_boot_option(vm, args_added="movable_node")
    session = vm.wait_for_login()
    mem_name = params["target_mems"]
    hotplug_test = MemoryHotplugTest(test, params, env)
    hotplug_test.hotplug_memory(vm, mem_name)
    hotplug_test.check_memory(vm)
    session.cmd(params["get_stress_ng"])
    session.cmd(params["compile_stress_ng"], timeout=360)
    try:
        run_stress = params["run_stress_ng"]
        stress_args = params["stress_ng_args"].split(";")
        for arg in stress_args:
            cmd = run_stress % arg
            status, output = session.cmd_status_output(cmd, timeout=1500)
            if status:
                test.fail("Stress_ng cmd '%s' failed with '%s'" % (cmd, output))
        hotplug_test.unplug_memory(vm, mem_name)
        hotplug_test.check_memory(vm)
        hotplug_test.hotplug_memory(vm, mem_name)
        hotplug_test.check_memory(vm)
        session = vm.reboot()
        hotplug_test.unplug_memory(vm, mem_name)
        hotplug_test.check_memory(vm)
    finally:
        if session:
            session.cmd_output_safe("rm -rf %s" % params["stress_ng_dir"])
            session.close()
