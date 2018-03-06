import logging

from virttest import error_context

from qemu.tests import numa_memdev_options
from qemu.tests.mlock_basic import MlockBasic


@error_context.context_aware
def run(test, params, env):
    """
    [Memory][Numa] NUMA memdev option test with mlock, this case will:
    1) Check host's numa node(s) amount.
    2) Get nr_mlock and nr_unevictable in host before VM start.
    3) Start the VM.
    4) Get nr_mlock and nr_unevictable in host after VM start.
    5) Check nr_mlock and nr_unevictable with VM memory.
    6) Check the policy.
    7) Check the memory in procfs.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Check host's numa node(s) amount!", logging.info)
    numa_memdev_options.check_host_numa_node_amount(test)

    numa_mlock_test = MlockBasic(test, params, env)
    numa_mlock_test.start()

    error_context.context("Check query-memdev!", logging.info)
    numa_memdev_options.check_query_memdev(test, params, numa_mlock_test.vm)

    error_context.context("Check the memory in procfs!", logging.info)
    numa_memdev_options.check_memory_in_procfs(test, params, numa_mlock_test.vm)
