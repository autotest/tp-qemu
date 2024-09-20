import math
import re

from avocado.utils import memory
from virttest import env_process, error_context, test_setup, utils_misc
from virttest.utils_numeric import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    Qemu allocate hugepage from specify node.
    Steps:
    1) Setup total of 4G mem hugepages for specify node.
    2) Setup total of 1G mem hugepages for idle node.
    3) Mount this hugepage to /mnt/kvm_hugepage.
    4) Boot guest only allocate hugepage from specify node.
    5) Check the hugepage used from every node.
    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """
    memory.drop_caches()
    hugepage_size = params.get_numeric("hugepage_size", memory.get_huge_page_size())
    mem_size = int(normalize_data_size("%sM" % params["mem"], "K"))
    idle_node_mem = int(normalize_data_size("%sM" % params["idle_node_mem"], "K"))

    error_context.context("Get host numa topological structure.", test.log.info)
    host_numa_node = utils_misc.NumaInfo()
    node_list = host_numa_node.get_online_nodes_withmem()
    idle_node_list = node_list.copy()
    node_meminfo = host_numa_node.get_all_node_meminfo()

    for node_id in node_list:
        error_context.base_context(
            "Check preprocess HugePages Free on host " "numa node %s." % node_id,
            test.log.info,
        )
        node_memfree = int(node_meminfo[node_id]["MemFree"])
        if node_memfree < idle_node_mem:
            idle_node_list.remove(node_id)
        if node_memfree < mem_size:
            node_list.remove(node_id)

    if len(idle_node_list) < 2 or not node_list:
        test.cancel(
            "Host node does not have enough nodes to run the test, " "skipping test..."
        )

    for node_id in node_list:
        error_context.base_context(
            "Specify qemu process only allocate " "HugePages from node%s." % node_id,
            test.log.info,
        )
        params["target_nodes"] = "%s" % node_id
        huge_pages_num = math.ceil(mem_size / hugepage_size)
        params["target_num_node%s" % node_id] = huge_pages_num
        error_context.context(
            "Setup huge pages for specify node%s." % node_id, test.log.info
        )
        check_list = [_ for _ in idle_node_list if _ != node_id]
        for idle_node in check_list:
            params["target_nodes"] += " %s" % idle_node
            params["target_num_node%s" % idle_node] = math.ceil(
                idle_node_mem / hugepage_size
            )
            error_context.context(
                "Setup huge pages for idle node%s." % idle_node, test.log.info
            )
        hp_config = test_setup.HugePageConfig(params)
        try:
            hp_config.setup()
            params["qemu_command_prefix"] = "numactl --membind=%s" % node_id
            params["start_vm"] = "yes"
            params["hugepage_path"] = hp_config.hugepage_path
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            vm = env.get_vm(params["main_vm"])
            try:
                vm.verify_alive()
                vm.wait_for_login()

                meminfo = host_numa_node.get_all_node_meminfo()
                for index in check_list:
                    error_context.base_context(
                        "Check process HugePages Free on host " "numa node %s." % index,
                        test.log.info,
                    )
                    hugepages_free = int(meminfo[index]["HugePages_Free"])
                    if int(node_meminfo[index]["HugePages_Free"]) > hugepages_free:
                        test.fail(
                            "Qemu still use HugePages from other node."
                            "Expect: node%s, used: node%s." % (node_id, index)
                        )
            finally:
                vm.destroy()
        except Exception as details:
            # Check if there have enough contiguous Memory on the host node
            details = str(details)
            if re.findall(r"Cannot set %s hugepages" % huge_pages_num, details):
                test.cancel(
                    "Host node does not have enough contiguous memory "
                    "to run the test, skipping test..."
                )
            test.error(details)
        finally:
            hp_config.cleanup()
            utils_misc.wait_for(
                lambda: int(hp_config.get_node_num_huge_pages(node_id, hugepage_size))
                == 0,
                first=2.0,
                timeout=10,
            )
