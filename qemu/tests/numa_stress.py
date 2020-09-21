import os
import re
import logging

from avocado.utils import process

from virttest import error_context
from virttest import utils_misc
from virttest import funcatexit
from virttest import utils_test
from virttest import data_dir
from virttest.staging import utils_memory


def max_mem_map_node(host_numa_node, qemu_pid):
    """
    Find the numa node which qemu process memory maps to it the most.

    :param numa_node_info: Host numa node information
    :type numa_node_info: NumaInfo object
    :param qemu_pid: process id of qemu
    :type numa_node_info: string
    :return: The node id and how many pages are mapped to it
    :rtype: tuple
    """
    node_list = host_numa_node.online_nodes
    memory_status, _ = utils_test.qemu.get_numa_status(host_numa_node, qemu_pid)
    node_map_most = 0
    memory_sz_map_most = 0
    for index in range(len(node_list)):
        if memory_sz_map_most < memory_status[index]:
            memory_sz_map_most = memory_status[index]
            node_map_most = node_list[index]
    return (node_map_most, memory_sz_map_most)


def get_tmpfs_write_speed():
    """
    Get the tmpfs write speed of the host
    return: The write speed of tmpfs, the unit is kb/s.
    """
    process.run("mkdir -p /tmp/test_speed && "
                "mount -t tmpfs none /tmp/test_speed", shell=True)
    output = process.run("dd if=/dev/urandom of=/tmp/test_speed/test "
                         "bs=1k count=1024")
    try:
        speed = re.search(r"\s([\w\s\.]+)/s", output.stderr, re.I).group(1)
        return float(utils_misc.normalize_data_size(speed, 'K', 1024))
    except Exception:
        return 3072
    finally:
        process.run("umount /tmp/test_speed")
        os.removedirs("/tmp/test_speed")


@error_context.context_aware
def run(test, params, env):
    """
    Qemu numa stress test:
    1) Boot up a guest and find the node it used
    2) Try to allocate memory in that node
    3) Run memory heavy stress inside guest
    4) Check the memory use status of qemu process
    5) Repeat step 2 ~ 4 several times


    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    host_numa_node = utils_misc.NumaInfo()
    if len(host_numa_node.online_nodes) < 2:
        test.cancel("Host only has one NUMA node, skipping test...")

    timeout = float(params.get("login_timeout", 240))
    test_count = int(params.get("test_count", 4))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    qemu_pid = vm.get_pid()

    if test_count < len(host_numa_node.online_nodes):
        test_count = len(host_numa_node.online_nodes)

    tmpfs_size = params.get_numeric("tmpfs_size")
    for node in host_numa_node.nodes:
        node_mem = int(host_numa_node.read_from_node_meminfo(node, "MemTotal"))
        if tmpfs_size == 0:
            tmpfs_size = node_mem
    tmpfs_path = params.get("tmpfs_path", "tmpfs_numa_test")
    tmpfs_path = utils_misc.get_path(data_dir.get_tmp_dir(), tmpfs_path)
    tmpfs_write_speed = get_tmpfs_write_speed()
    dd_timeout = tmpfs_size / tmpfs_write_speed * 1.5
    mount_fs_size = "size=%dK" % tmpfs_size
    memory_file = utils_misc.get_path(tmpfs_path, "test")
    dd_cmd = "dd if=/dev/urandom of=%s bs=1k count=%s" % (memory_file,
                                                          tmpfs_size)
    utils_memory.drop_caches()

    if utils_memory.freememtotal() < tmpfs_size:
        test.cancel("Host does not have enough free memory to run the test, "
                    "skipping test...")

    if not os.path.isdir(tmpfs_path):
        os.mkdir(tmpfs_path)

    test_mem = float(params.get("mem"))*float(params.get("mem_ratio", 0.8))
    stress_args = "--cpu 4 --io 4 --vm 2 --vm-bytes %sM" % int(test_mem / 2)
    most_used_node, memory_used = max_mem_map_node(host_numa_node, qemu_pid)

    for test_round in range(test_count):
        if os.path.exists(memory_file):
            os.remove(memory_file)
        utils_memory.drop_caches()
        if utils_memory.freememtotal() < tmpfs_size:
            test.error("Don't have enough memory to execute this "
                       "test after %s round" % test_round)
        error_context.context("Executing stress test round: %s" % test_round,
                              logging.info)
        numa_node_malloc = most_used_node
        numa_dd_cmd = "numactl -m %s %s" % (numa_node_malloc, dd_cmd)
        error_context.context("Try to allocate memory in node %s"
                              % numa_node_malloc, logging.info)
        try:
            utils_misc.mount("none", tmpfs_path, "tmpfs", perm=mount_fs_size)
            funcatexit.register(env, params.get("type"), utils_misc.umount,
                                "none", tmpfs_path, "tmpfs")
            process.system(numa_dd_cmd, timeout=dd_timeout, shell=True)
        except Exception as error_msg:
            if "No space" in str(error_msg):
                pass
            else:
                test.fail("Can not allocate memory in node %s."
                          " Error message:%s" % (numa_node_malloc,
                                                 str(error_msg)))
        error_context.context("Run memory heavy stress in guest", logging.info)
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
        error_context.context("Get the qemu process memory use status",
                              logging.info)
        node_after, memory_after = max_mem_map_node(host_numa_node, qemu_pid)
        if node_after == most_used_node and memory_after >= memory_used:
            test.fail("Memory still stick in node %s" % numa_node_malloc)
        else:
            most_used_node = node_after
            memory_used = memory_after
        stress_test.unload_stress()
        stress_test.clean()
        utils_misc.umount("none", tmpfs_path, "tmpfs")
        funcatexit.unregister(env, params.get("type"), utils_misc.umount,
                              "none", tmpfs_path, "tmpfs")
        session.cmd("sync; echo 3 > /proc/sys/vm/drop_caches")
        utils_memory.drop_caches()

    session.close()
