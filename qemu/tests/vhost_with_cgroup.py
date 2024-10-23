from avocado.utils import process
from virttest import error_context
from virttest.env_process import preprocess
from virttest.staging.utils_cgroup import Cgroup, CgroupModules


@error_context.context_aware
def run(test, params, env):
    """
    Test Step:
        1. boot guest with vhost enabled
        2. add vhost-%pid_qemu process to a cgroup
        3. check the vhost process join to the cgroup successfully

        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    def assign_vm_into_cgroup(vm, cgroup, pwd=None):
        """
        Assigns all threads of VM into cgroup
        :param vm: desired VM
        :param cgroup: cgroup handler
        :param pwd: desired cgroup's pwd, cgroup index or None for root cgroup
        """
        cgroup.set_cgroup(vm.get_shell_pid(), pwd)
        for pid in process.get_children_pids(vm.get_shell_pid()):
            try:
                cgroup.set_cgroup(int(pid), pwd)
            except Exception:  # Process might not already exist
                test.fail("Failed to move all VM threads to cgroup")

    error_context.context("Test Setup: Cgroup initialize in host", test.log.info)
    modules = CgroupModules()
    if modules.init(["cpu"]) != 1:
        test.fail("Can't mount cpu cgroup modules")

    cgroup = Cgroup("cpu", "")
    cgroup.initialize(modules)

    error_context.context(
        "Boot guest and attach vhost to cgroup your" " setting(cpu)", test.log.info
    )
    params["start_vm"] = "yes"
    preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    timeout = int(params.get("login_timeout", 360))
    vm.wait_for_login(timeout=timeout)

    cgroup.mk_cgroup()
    cgroup.set_property("cpu.cfs_period_us", 100000, 0)
    assign_vm_into_cgroup(vm, cgroup, 0)

    vhost_pids = process.system_output("pgrep vhost", shell=True).decode()
    if not vhost_pids:
        test.error("Vhost process does not exist")
    test.log.info("Vhost have started with pid %s", vhost_pids)
    for vhost_pid in vhost_pids.strip().split():
        cgroup.set_cgroup(int(vhost_pid))

    error_context.context(
        "Check whether vhost attached to" " cgroup successfully", test.log.info
    )
    cgroup_tasks = " ".join(cgroup.get_property("tasks"))
    for vhost_pid in vhost_pids.strip().split():
        if vhost_pid not in cgroup_tasks:
            test.error(
                "vhost process attach to cgroup FAILED!"
                " Tasks in cgroup is:%s" % cgroup_tasks
            )
    test.log.info("Vhost process attach to cgroup successfully")
