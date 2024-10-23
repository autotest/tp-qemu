from avocado.utils import process
from virttest import env_process, error_context
from virttest.staging import utils_memory
from virttest.utils_numeric import normalize_data_size
from virttest.utils_test.qemu import MemoryHotplugTest


@error_context.context_aware
def run(test, params, env):
    """
    Memory share and discard-data hotplug test
    1) Setup hugepages
    2) Mount /mnt/kvm_hugepage
    3) Boot guest with one numa node
    4) Hotplug 1G memory
    5) Check memory
    6) Unplug memory
    7) Check memory
    8) Check results for discard-data value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    timeout = int(params.get("login_timeout", 240))

    mem_dev = params.get("mem_devs")
    size_mem = int(normalize_data_size(params["size_mem_%s" % mem_dev], "K"))
    total_hg_size = size_mem

    target_mem = params.get("target_mems")
    if params.get("backend_mem_%s" % target_mem) == "memory-backend-file":
        size_target_mem = int(
            normalize_data_size(params["size_mem_%s" % target_mem], "K")
        )
        total_hg_size += size_target_mem

    hp_size = utils_memory.read_from_meminfo("Hugepagesize")
    params["target_hugepages"] = int(total_hg_size // hp_size)
    params["setup_hugepages"] = "yes"
    params["not_preprocess"] = "no"

    env_process.preprocess(test, params, env)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    hotplug_test = MemoryHotplugTest(test, params, env)
    hotplug_test.hotplug_memory(vm, target_mem)
    hotplug_test.check_memory(vm)
    hotplug_test.unplug_memory(vm, target_mem)
    hotplug_test.check_memory(vm)

    session.close()
    error_context.context("Shutdown guest...", test.log.debug)
    vm.destroy()

    hp_total = int(utils_memory.read_from_meminfo("HugePages_Total"))
    hp_free = int(utils_memory.read_from_meminfo("HugePages_Free"))

    error_context.context("hp_total: %s" % str(hp_total), test.log.debug)
    error_context.context("hp_free: %s" % str(hp_free), test.log.debug)

    if params.get("backend_mem_plug1") == "memory-backend-file":
        if not params.get_boolean("discard-data_plug1", True):
            try:
                process.system("ls %s" % params["mem-path_plug1"])
            except process.CmdError:
                test.fail("Error, %s not found." % params["mem-path_plug1"])

            op = (hp_total - hp_free) * (hp_size / 1024)
            hp_used = int(normalize_data_size("%sM" % str(op), "K"))

            error_context.context("hp_used: %s" % str(hp_used), test.log.debug)

            if hp_used != size_target_mem:
                test.fail("Error, total hugepages doesn't match with used memory")
        elif hp_total != hp_free:
            test.fail("Error, free hugepages doesn't match with total hugepages")
        # Deletes the mem-path file to avoid test error
        process.system("rm -rf %s" % params["mem-path_plug1"])
        # Compares free and total memory values after deleting mem-path file
        hp_free_after_delete = int(utils_memory.read_from_meminfo("HugePages_Free"))
        if hp_total != hp_free_after_delete:
            test.fail(
                "Error, free hugepages doesn't match with total hugepages after "
                "deleting mem-path file"
            )
