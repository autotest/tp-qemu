import math
import os
import time

from avocado.utils import process
from virttest import error_context, utils_test
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    Run stress as a memory stress in guest for THP testing

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    nr_ah = []

    debugfs_flag = 1
    debugfs_path = os.path.join(test.tmpdir, "debugfs")
    mem = int(params.get("mem"))
    qemu_mem = int(params.get("qemu_mem", "64"))
    hugetlbfs_path = params.get("hugetlbfs_path", "/proc/sys/vm/nr_hugepages")
    vm = env.get_vm(params["main_vm"])

    error_context.context("smoke test setup")
    if not os.path.ismount(debugfs_path):
        if not os.path.isdir(debugfs_path):
            os.makedirs(debugfs_path)
        try:
            process.system("mount -t debugfs none %s" % debugfs_path, shell=True)
        except Exception:
            debugfs_flag = 0

    try:
        # Allocated free memory to hugetlbfs
        mem_free = int(utils_memory.read_from_meminfo("MemFree")) / 1024
        mem_swap = int(utils_memory.read_from_meminfo("SwapFree")) / 1024
        hugepage_size = int(utils_memory.read_from_meminfo("Hugepagesize")) / 1024
        nr_hugetlbfs = math.ceil((mem_free + mem_swap - mem - qemu_mem) / hugepage_size)
        fd = open(hugetlbfs_path, "w")
        fd.write(str(nr_hugetlbfs))
        fd.close()

        error_context.context("Memory stress test")

        nr_ah.append(int(utils_memory.read_from_meminfo("AnonHugePages")))
        if nr_ah[0] <= 0:
            test.fail("VM is not using transparent hugepage")

        # Run stress memory heavy in guest
        test_mem = float(mem) * float(params.get("mem_ratio", 0.8))
        stress_args = "--cpu 4 --io 4 --vm 2 --vm-bytes %sM" % int(test_mem / 2)
        stress_test = utils_test.VMStress(vm, "stress", params, stress_args=stress_args)
        stress_test.load_stress_tool()
        time.sleep(int(params.get("stress_time", 120)))
        nr_ah.append(int(utils_memory.read_from_meminfo("AnonHugePages")))
        test.log.debug("The huge page using for guest is: %s", nr_ah)

        if nr_ah[1] <= nr_ah[0]:
            test.log.warning("VM don't use transparent hugepage while memory stress")

        if debugfs_flag == 1:
            if int(open(hugetlbfs_path, "r").read()) <= 0:
                test.fail("KVM doesn't use transparenthugepage")

        test.log.info("memory stress test finished")
        stress_test.unload_stress()
        stress_test.clean()
    finally:
        error_context.context("all tests cleanup")
        fd = open(hugetlbfs_path, "w")
        fd.write("0")
        fd.close()
        if os.path.ismount(debugfs_path):
            process.run("umount %s" % debugfs_path, shell=True)
        if os.path.isdir(debugfs_path):
            os.removedirs(debugfs_path)
