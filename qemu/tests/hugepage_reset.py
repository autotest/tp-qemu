import time
import logging

from virttest import env_process
from virttest import test_setup
from virttest import utils_test
from virttest import utils_misc
from virttest import error_context
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    Re-assign nr-hugepages

    1. Set up hugepage with 1G page size and hugepages=8
    2. Boot up guest using /mnt/kvm_hugepage as backend in QEMU CML
    3. Change the nr_hugepages after the guest boot up (6 and 10)
    4. Run the stress test **inside guest**
    5. change the nr_hugepages after the stress test (6 and 10)

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def set_hugepage():
        """Set nr_hugepages"""
        for h_size in (origin_nr - 2, origin_nr + 2):
            hp_config.target_hugepages = h_size
            hp_config.set_hugepages()
            if params.get('on_numa_node'):
                logging.info('Set hugepage size %s to target node %s',
                             h_size, target_node)
                hp_config.set_node_num_huge_pages(h_size, target_node,
                                                  hugepage_size)

    origin_nr = int(params['origin_nr'])
    host_numa_node = utils_misc.NumaInfo()
    mem = int(float(utils_misc.normalize_data_size("%sM" % params["mem"])))
    if params.get('on_numa_node'):
        for target_node in host_numa_node.get_online_nodes_withmem():
            node_mem_free = host_numa_node.read_from_node_meminfo(
                target_node, 'MemFree')
            if int(node_mem_free) > mem:
                params['target_nodes'] = target_node
                params["qemu_command_prefix"] = ("numactl --membind=%s" %
                                                 target_node)
                params['target_num_node%s' % target_node] = origin_nr
                break
            logging.info(
                'The free memory of node %s is %s, is not enough for'
                ' guest memory: %s', target_node, node_mem_free, mem)
        else:
            test.cancel("No node on your host has sufficient free memory for "
                        "this test.")
    hp_config = test_setup.HugePageConfig(params)
    hp_config.target_hugepages = origin_nr
    logging.info('Setup hugepage number to %s', origin_nr)
    hp_config.setup()
    hugepage_size = utils_memory.get_huge_page_size()
    params["hugepage_path"] = hp_config.hugepage_path
    params['start_vm'] = "yes"
    vm_name = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    params['stress_args'] = '--vm %s --vm-bytes 256M --timeout 30s' % (
            mem // 512)
    logging.info('Loading stress on guest.')
    stress = utils_test.VMStress(vm, 'stress', params)
    stress.load_stress_tool()
    time.sleep(30)
    stress.unload_stress()
    set_hugepage()
    hp_config.cleanup()
    vm.verify_kernel_crash()
