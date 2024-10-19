import time

from avocado.utils import process
from virttest import error_context
from virttest.utils_numeric import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    1) Start guest with 10 rbd data disks and system disk.
    2) Check the block info for 1 hour
    3) Check the used memory size is not increased

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_qemu_vmrss():
        pid = vm.process.get_pid()
        qemu_stat_file = "/proc/" + str(pid) + "/status"
        used_mem_cmd = (
            "cat %s | grep VmRSS | awk -F ':\t* *' '{print $2}'" % qemu_stat_file
        )
        used_mem_size = process.system_output(used_mem_cmd, shell=True)
        used_mem_size_byte = normalize_data_size(
            str(used_mem_size), order_magnitude="B"
        )
        return used_mem_size_byte

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # Wait the guest boot up completely
    login_timeout = int(params.get("login_timeout", 360))
    vm.wait_for_login(timeout=login_timeout)

    used_mem_size_before = _get_qemu_vmrss()
    test.log.info(
        "The qemu-kvm process used mem size before querying blocks is %s",
        used_mem_size_before,
    )

    test.log.info("Begin to query blocks for 1 hour.")
    timeout = time.time() + 60 * 60 * 1  # 1 hour from now
    while True:
        if time.time() > timeout:
            break
        vm.monitor.cmd("query-blockstats")
        vm.monitor.cmd("query-block")

    used_mem_size_after = _get_qemu_vmrss()
    test.log.info(
        "The qemu-kvm process used mem size after querying blocks is %s",
        used_mem_size_after,
    )
    test.log.info("Check whether the used memory size is increased.")
    if int(used_mem_size_after) > int(used_mem_size_before) * 1.2:
        test.fail(
            "The used memory size before is %s, but after checking the blocks "
            "for 1 hour, it increased to %s. There should be memory leaks, "
            "check please." % (used_mem_size_before, used_mem_size_after)
        )
