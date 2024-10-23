from avocado.utils import process
from virttest.staging import utils_memory
from virttest.utils_misc import normalize_data_size, wait_for
from virttest.utils_test.qemu import MemoryHotplugTest


def run(test, params, env):
    """
    Qemu memory hotplug test:
    1) Boot guest with -m option
    2) Hotplug memory to guest with option reserve enable/disabled
    3) Check memory inside guest
    4) Check hugepages on host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_hp_rsvd():
        """
        A generator to get HugePages_Rsvd until it does not change
        """
        stable = False
        hp_rsvd = utils_memory.read_from_meminfo("HugePages_Rsvd")
        while True:
            yield stable
            cur_rsvd = utils_memory.read_from_meminfo("HugePages_Rsvd")
            stable = cur_rsvd == hp_rsvd
            hp_rsvd = cur_rsvd

    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()
    mem_name = params["target_mems"]
    hp_size = utils_memory.read_from_meminfo("Hugepagesize")
    hp_total = utils_memory.read_from_meminfo("HugePages_Total")
    size_target_mem = params["size_mem_%s" % mem_name]
    hp_target = int(float(normalize_data_size(size_target_mem, "K")) / hp_size) + int(
        hp_total
    )
    process.system("echo %s > /proc/sys/vm/nr_hugepages" % hp_target, shell=True)
    hotplug_test = MemoryHotplugTest(test, params, env)
    hotplug_test.hotplug_memory(vm, mem_name)
    hotplug_test.check_memory(vm)
    timeout = int(params.get("check_timeout", 60))
    rsvd_is_stable = get_hp_rsvd()
    if not wait_for(lambda: next(rsvd_is_stable), timeout, 5, 3):
        test.error("HugePages_Rsvd is not stable in %ss" % timeout)
    try:
        hugepage_rsvd = utils_memory.read_from_meminfo("HugePages_Rsvd")
        test.log.info("HugePages_Rsvd is %s after hotplug memory", hugepage_rsvd)
        if params["reserve_mem"] == "yes":
            hugepages_total = utils_memory.read_from_meminfo("HugePages_Total")
            hugepages_free = utils_memory.read_from_meminfo("HugePages_Free")
            hugepagesize = utils_memory.read_from_meminfo("Hugepagesize")
            test.log.info(
                "HugePages_Total is %s, hugepages_free is %s",
                hugepages_total,
                hugepages_free,
            )
            plug_size = params["size_mem_%s" % mem_name]
            numa_size = params["size_mem_%s" % params["mem_devs"]]
            expected_size = float(normalize_data_size(plug_size, "K")) + float(
                normalize_data_size(numa_size, "K")
            )
            page_number = hugepages_total - hugepages_free + hugepage_rsvd
            if page_number * hugepagesize != int(expected_size):
                test.fail(
                    "HugePages_Total - HugePages_Free + HugePages_Rsvd is"
                    "not equal to memory backend size"
                )
        else:
            if hugepage_rsvd != 0:
                test.fail("HugePages_Rsvd is not 0 when reserve option is off")
    finally:
        vm.destroy()
