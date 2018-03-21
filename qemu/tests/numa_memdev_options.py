import logging

from avocado.utils import process

from virttest import error_context
from virttest import utils_misc
from virttest.staging import utils_memory


def check_host_numa_node_amount(test):
    """
    Check host NUMA node amount

    :param test: QEMU test object
    """
    host_numa_nodes = utils_memory.numa_nodes()
    host_numa_nodes = len(host_numa_nodes)
    if host_numa_nodes < 2:
        test.cancel("The host numa nodes should be at least 2! But there is %d."
                    % host_numa_nodes)


def check_query_memdev(test, params, vm):
    """
    Check memory info in query-memdev

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    """
    mem_devs = params['mem_devs'].split()
    query_list = vm.monitor.info("memdev")
    if len(mem_devs) != len(query_list):
        test.fail("%d memory devices in query-memdev, but not %d!"
                  " query-memdev: %s"
                  % (len(query_list), len(mem_devs),
                     [item["id"] for item in query_list]))
    policy = params['policy_mem']
    for dev in query_list:
        mem_dev = dev['id'].split('-')[1]
        memdev_params = params.object_params(mem_dev)
        if dev['policy'] != policy:
            test.fail("memdev = %s: 'policy' is '%s', but not '%s'!"
                      % (mem_dev, dev['policy'], policy))
        prealloc = (memdev_params['prealloc'] == 'yes')
        if dev['prealloc'] != prealloc:
            test.fail("memdev = %s: 'prealloc' is not '%s'!"
                      % (mem_dev, memdev_params['prealloc']))
        if policy == 'default':
            continue
        host_node = str(dev['host-nodes'][0])
        if host_node != memdev_params['host-nodes']:
            test.fail("memdev = %s: 'host-nodes' is '%s', but not '%s'!"
                      % (mem_dev, host_node, memdev_params["host-nodes"]))


def check_memory_in_procfs(test, params, vm):
    """
    Check memory info in procfs

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    """
    qemu_pid = vm.get_pid()
    policy = params['policy_mem']
    if policy == 'preferred':
        policy = 'prefer'
    mem_path = params.get("mem-path", None)
    for mem_dev in params['mem_devs'].split():
        memdev_params = params.object_params(mem_dev)
        mem_size = memdev_params['size']
        mem_size = int(float(utils_misc.normalize_data_size(mem_size, "K")))
        smaps = process.system_output("grep -1 %d /proc/%d/smaps"
                                      % (mem_size, qemu_pid))
        if mem_path and (mem_path not in smaps):
            test.fail("memdev = %s: mem-path '%s' is not in smaps '%s'!"
                      % (mem_dev, mem_path, smaps))
        mem_start = smaps.split('-')[0]
        numa_maps = process.system_output("grep %s /proc/%d/numa_maps"
                                          % (mem_start, qemu_pid))
        if mem_path and (mem_path not in numa_maps):
            test.fail("memdev = %s: mem-path '%s' is not in numa_maps '%s'!"
                      % (mem_dev, mem_path, numa_maps))
        policy_numa = numa_maps.split()[1].split(':')
        if policy != policy_numa[0]:
            test.fail("memdev = %s:"
                      " 'policy' in numa_maps is '%s', but not '%s'!"
                      % (mem_dev, policy_numa[0], policy))
        elif (policy != 'default'):
            host_node = memdev_params['host-nodes']
            if (policy_numa[1] != host_node):
                test.fail("memdev = %s:"
                          " 'host-nodes' in numa_maps is '%s', but not '%s'!"
                          % (mem_dev, policy_numa[1], host_node))


@error_context.context_aware
def run(test, params, env):
    """
    [Memory][Numa] NUMA memdev option, this case will:
    1) Check host's numa node(s) amount.
    2) Start the VM.
    3) Check query-memdev.
    4) Check the memory in procfs.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error_context.context("Check host's numa node(s) amount!", logging.info)
    check_host_numa_node_amount(test)

    error_context.context("Starting VM!", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Check query-memdev!", logging.info)
    check_query_memdev(test, params, vm)

    error_context.context("Check the memory in procfs!", logging.info)
    check_memory_in_procfs(test, params, vm)
