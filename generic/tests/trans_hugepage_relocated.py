import re
import time

from avocado.utils import process
from virttest import utils_test
from virttest.staging import utils_memory

from provider import thp_fragment_tool


def run(test, params, env):
    """
    Transparent hugepage relocated test with quantification.
    The pages thp deamon will scan for one round set to 4096, and the sleep
    time will be set to 10 seconds. And alloc sleep time is set to 1 minute.
    So the hugepage size should increase 16M every 10 seconds, and when system
    is busy and it failed to allocate hugepage for guest, the value will keep
    the same in 1 minute. We will check that value every 10 seconds and check
    if it is following the rules.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def nr_hugepage_check(sleep_time, wait_time):
        time_last = 0
        while True:
            value = int(utils_memory.read_from_meminfo("AnonHugePages"))
            test.log.debug("The AnonHugePages value: %d", value)
            nr_hugepages.append(value)
            time_stamp = time.time()
            if time_last != 0:
                if nr_hugepages[-2] != nr_hugepages[-1]:
                    time_last = time_stamp
                elif time_stamp - time_last > wait_time:
                    test.log.info("Huge page size stop changed")
                    break
            else:
                time_last = time_stamp
            time.sleep(sleep_time)

    test.log.info("Relocated test start")
    login_timeout = float(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    free_memory = utils_memory.read_from_meminfo("MemFree")
    hugepage_size = utils_memory.read_from_meminfo("Hugepagesize")
    mem = params.get_numeric("mem")
    vmsm = mem + 128
    hugetlbfs_path = params.get("hugetlbfs_path", "/proc/sys/vm/nr_hugepages")
    if vmsm < int(free_memory) / 1024:
        nr_hugetlbfs = int(vmsm * 1024 / hugepage_size)
    else:
        nr_hugetlbfs = None
    # Get dd speed in host
    start_time = time.time()
    cmd = "dd if=/dev/urandom of=/tmp/speed_test bs=4K count=256"
    process.run(cmd, verbose=False, shell=True)
    end_time = time.time()
    dd_timeout = vmsm * (end_time - start_time) * 2
    nr_hugepages = []
    thp_cfg = params.get("thp_test_config")
    s_time = int(re.findall(r"scan_sleep_millisecs:(\d+)", thp_cfg)[0]) / 1000
    w_time = int(re.findall(r"alloc_sleep_millisecs:(\d+)", thp_cfg)[0]) / 1000

    test.log.info("Turn off swap in guest")
    s, o = session.cmd_status_output("swapoff -a")
    if s != 0:
        test.log.warning("Didn't turn off swap in guest")
    s, o = session.cmd_status_output("cat /proc/meminfo")
    mem_free_filter = r"MemFree:\s+(.\d+)\s+(\w+)"
    guest_mem_free, guest_unit = re.findall(mem_free_filter, o)[0]
    if re.findall("[kK]", guest_unit):
        guest_mem_free = int(guest_mem_free) / 1024
    elif re.findall("[gG]", guest_unit):
        guest_mem_free = int(guest_mem_free) * 1024
    elif re.findall("[mM]", guest_unit):
        pass
    else:
        guest_mem_free = int(guest_mem_free) / 1024 / 1024

    file_size = min(1024, int(guest_mem_free / 2))
    cmd = "mount -t tmpfs -o size=%sM none /mnt" % file_size
    s, o = session.cmd_status_output(cmd)
    if nr_hugetlbfs:
        with open(hugetlbfs_path, "w") as hugepage_cfg:
            hugepage_cfg.write(str(nr_hugetlbfs))

    test.log.info("THP fragment tool starts")
    thp_fragment_tool.execute_tool(test)

    bg = utils_test.BackgroundTest(nr_hugepage_check, (s_time, w_time))
    bg.start()

    while bg.is_alive():
        count = file_size / 2
        cmd = "dd if=/dev/urandom of=/mnt/test bs=2M count=%s" % count
        s, o = session.cmd_status_output(cmd, dd_timeout)

    if bg:
        bg.join()
    mem_increase_step = int(re.findall(r"pages_to_scan:(\d+)", thp_cfg)[0]) / 512
    mem_increase = 0
    w_step = w_time / s_time + 1
    count = 0
    last_value = nr_hugepages.pop()
    while len(nr_hugepages) > 0:
        current = nr_hugepages.pop()
        if current == last_value:
            count += 1
        elif current < last_value:
            if last_value - current < mem_increase_step * 0.95:
                test.error("Hugepage memory increased too slow")
            mem_increase += last_value - current
            count = 0
        if count > w_step:
            test.log.warning("Memory didn't increase in %s s", (count * s_time))
    test.log.debug("The total mem_increase: %d", mem_increase)
    if mem_increase < file_size * 0.5:
        test.error(
            "Hugepages allocated can not reach a half: %s/%s"
            % (mem_increase, file_size)
        )
    session.close()
    test.log.info("Relocated test succeed")
