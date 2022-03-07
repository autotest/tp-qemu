import math

from avocado.utils import memory
from avocado.utils import process

from virttest import env_process
from virttest import error_context
from virttest import test_setup
from virttest import utils_misc

from virttest.utils_numeric import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    Qemu allocate hugepage from specify node.
    Steps:
    1) Setup total of 4G mem hugepages for specify node.
    2) Setup total of 1G mem hugepages for idle node.
    3) Mount this hugepage to /mnt/kvm_hugepage.
    4) Check the basic page size on arm host and guest.
    5) Boot guest only allocate hugepage from specify node.
    6) Check the hugepage used from every node.
    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    get_page_size = params.get('get_page_size')

    memory.drop_caches()
    hugepage_size = memory.get_huge_page_size()
    mem_size = int(normalize_data_size("%sM" % params["mem"], "K"))
    idle_node_mem = int(normalize_data_size("%sM" % params["idle_node_mem"], "K"))

    error_context.context("Get host numa topological structure.", test.log.info)
    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.get_online_nodes_withmem()
    idle_node_list = node_list.copy()
    node_meminfo = host_numa_node.get_all_node_meminfo()

    for node_id in node_list:
        error_context.base_context("Check preprocess HugePages Free on host "
                                   "numa node %s." % node_id, test.log.info)
        node_memfree = int(node_meminfo[node_id]["MemFree"])
        if node_memfree < idle_node_mem:
            idle_node_list.remove(node_id)
        if node_memfree < mem_size:
            node_list.remove(node_id)

    if 'arm64' in params['machine_type']:
        host_page_size = process.system_output(get_page_size).decode()
        if host_page_size != params.get("page_size"):
            test.fail("Host page size is %s not as expected." % host_page_size)
    if len(idle_node_list) < 2 or not node_list:
        test.cancel("Host node does not have enough nodes to run the test, "
                    "skipping test...")

    for node_id in node_list:
        error_context.base_context("Specify qemu process only allocate "
                                   "HugePages from node%s." % node_id, test.log.info)
        params["target_nodes"] = "%s" % node_id
        params["target_num_node%s" % node_id] = math.ceil(mem_size / hugepage_size)
        error_context.context("Setup huge pages for specify node%s." %
                              node_id, test.log.info)
        check_list = [_ for _ in idle_node_list if _ != node_id]
        for idle_node in check_list:
            params["target_nodes"] += " %s" % idle_node
            params["target_num_node%s" % idle_node] = math.ceil(idle_node_mem / hugepage_size)
            error_context.context("Setup huge pages for idle node%s." %
                                  idle_node, test.log.info)
        params["setup_hugepages"] = "yes"
        hp_config = test_setup.HugePageConfig(params)
        hp_config.setup()
        params["qemu_command_prefix"] = "numactl --membind=%s" % node_id
        params["start_vm"] = "yes"
        params["hugepage_path"] = hp_config.hugepage_path
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        try:
            vm = env.get_vm(params["main_vm"])
            vm.verify_alive()
            session = vm.wait_for_login()

            if 'arm64' in params['machine_type']:
                guest_page_size = session.cmd(get_page_size).strip()
                if guest_page_size != params.get("page_size"):
                    test.fail("Guest page size is %s not as expected." % guest_page_size)
            meminfo = host_numa_node.get_all_node_meminfo()
            for index in check_list:
                error_context.base_context("Check process HugePages Free on host "
                                           "numa node %s." % index, test.log.info)
                hugepages_free = int(meminfo[index]["HugePages_Free"])
                if int(node_meminfo[index]["HugePages_Free"]) > hugepages_free:
                    test.fail("Qemu still use HugePages from other node."
                              "Expect: node%s, used: node%s." % (node_id, index))
        finally:
            vm.destroy()
            hp_config.cleanup()
