import os
import re
import logging
import time
import errno

from avocado.utils import process

from virttest import error_context
from virttest import utils_misc
from virttest import funcatexit
from virttest import utils_test
from virttest import data_dir
from virttest import utils_package
from virttest.staging import utils_memory
from virttest.utils_test import BackgroundTest


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

    def heavyload_install():
        test_installed_cmd = 'dir "%s" | findstr /I heavyload' % install_path
        if session.cmd_status(test_installed_cmd) != 0:
            logging.warning("Could not find installed heavyload in guest, will"
                            " install it via winutils.iso ")
            winutil_drive = utils_misc.get_winutils_vol(session)
            if not winutil_drive:
                test.cancel("WIN_UTILS CDROM not found.")
            install_cmd = params["install_cmd"] % winutil_drive
            session.cmd(install_cmd)

    def run_stress():
        if os_type == 'linux':
            start_cmd = "stress %s > /dev/null &" % stress_args
            session.cmd_output_safe(start_cmd)
            if not utils_misc.wait_for(stress_test.app_running,
                                       stress_test.stress_wait_for_timeout,
                                       first=2.0,
                                       text="wait for stress app to start",
                                       step=1.0):
                raise test.error("Stress app does not running as expected")
            time.sleep(stress_time)
        else:
            heavyload_bin = r'"%s\heavyload.exe" ' % install_path
            heavyload_options = ["/CPU %d" % maxcpus,
                                 "/MEMORY %d" % test_mem,
                                 "/DURATION %d" % (stress_time // 60),
                                 "/START"]
            start_cmd = heavyload_bin + " ".join(heavyload_options)
            stress_tool = BackgroundTest(session.cmd, (start_cmd, stress_time,
                                                       stress_time))
            stress_tool.start()
            if not utils_misc.wait_for(stress_tool.is_alive, 60,
                                       first=5):
                test.error("Failed to start heavyload process.")
            stress_tool.join(stress_time)

    host_numa_node = utils_misc.NumaInfo()
    if len(host_numa_node.online_nodes) < 2:
        test.cancel("Host only has one NUMA node, skipping test...")

    if not utils_package.package_install('numad'):
        logging.error("Numad package is not installed")

    check_numad_status = params["check_numad_status"]
    start_numad_service = params.get("start_numad_service")
    if process.system(check_numad_status, ignore_status=True):
        process.system(start_numad_service)

    timeout = float(params.get("login_timeout", 240))
    stress_time = int(params.get("stress_time", 60))
    test_count = int(params.get("test_count", 4))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    maxcpus = vm.cpuinfo.maxcpus
    session = vm.wait_for_login(timeout=timeout)

    qemu_pid = vm.get_pid()

    if test_count < len(host_numa_node.online_nodes):
        test_count = len(host_numa_node.online_nodes)

    tmpfs_path = params.get("tmpfs_path", "tmpfs_numa_test")
    tmpfs_path = utils_misc.get_path(data_dir.get_tmp_dir(), tmpfs_path)
    tmpfs_write_speed = get_tmpfs_write_speed()
    memory_file = utils_misc.get_path(tmpfs_path, "test")
    utils_memory.drop_caches()

    if not os.path.isdir(tmpfs_path):
        os.mkdir(tmpfs_path)

    test_mem = float(params.get("mem"))*float(params.get("mem_ratio", 0.8))
    most_used_node, memory_used = max_mem_map_node(host_numa_node, qemu_pid)
    os_type = params["os_type"]

    if os_type == "windows":
        install_path = params["install_path"]
        heavyload_install()
    else:
        stress_args = "--cpu %s --vm-bytes %sM --timeout %s" % (maxcpus,
                                                                test_mem,
                                                                stress_time)
        stress_test = utils_test.VMStress(vm, "stress", params,
                                          stress_args=stress_args)
        stress_test.install()

    for test_round in range(test_count):
        if os.path.exists(memory_file):
            os.remove(memory_file)
        utils_memory.drop_caches()
        error_context.context("Executing stress test round: %s" % test_round,
                              logging.info)
        numa_node_malloc = most_used_node
        tmpfs_size = int(host_numa_node.read_from_node_meminfo(numa_node_malloc,
                                                               "MemFree"))
        if utils_memory.freememtotal() - tmpfs_size < 1024*1024:
            test.cancel("Host does not have enough free memory to run the test,"
                        "skipping test...")
        dd_timeout = tmpfs_size / tmpfs_write_speed * 1.5
        mount_fs_size = "size=%dK" % tmpfs_size
        dd_cmd = "dd if=/dev/urandom of=%s bs=1k count=%s" % (memory_file,
                                                              tmpfs_size)
        numa_dd_cmd = "numactl -m %s %s" % (numa_node_malloc, dd_cmd)
        error_context.context("Try to allocate memory in node %s"
                              % numa_node_malloc, logging.info)
        try:
            utils_misc.mount("none", tmpfs_path, "tmpfs", perm=mount_fs_size)
            funcatexit.register(env, params.get("type"), utils_misc.umount,
                                "none", tmpfs_path, "tmpfs")
            try:
                process.system(numa_dd_cmd, timeout=dd_timeout, shell=True)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    pass
                else:
                    test.fail("Can not allocate memory in node %s."
                              " Error message:%s" % (numa_node_malloc, str(e)))
            error_context.context("Run memory heavy stress in guest",
                                  logging.info)
            run_stress()
            error_context.context("Get the qemu process memory use status",
                                  logging.info)
            node_after, memory_after = max_mem_map_node(host_numa_node,
                                                        qemu_pid)
            if node_after == most_used_node and memory_after >= memory_used:
                test.fail("Memory still stick in node %s" % numa_node_malloc)
            else:
                most_used_node = node_after
                memory_used = memory_after
        finally:
            utils_misc.umount("none", tmpfs_path, "tmpfs")
            funcatexit.unregister(env, params.get("type"), utils_misc.umount,
                                  "none", tmpfs_path, "tmpfs")
            utils_memory.drop_caches()

    session.close()
