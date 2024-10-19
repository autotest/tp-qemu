import math
import os

from avocado.utils import process
from virttest import env_process, error_context
from virttest.staging import utils_memory
from virttest.utils_misc import normalize_data_size


@error_context.context_aware
def run(test, params, env):
    """
    KVM khugepage user side test:
    1) Verify that the hugepages can be swapped in/out.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def get_mem_info(mem_check_list):
        """
        Get mem info from /proc/meminfo, with magnitude "M"
        """
        mem_info = {}
        for key in mem_check_list:
            value = utils_memory.read_from_meminfo(key)
            mem_info[key] = int(float(normalize_data_size("%s kB" % value)))
        return mem_info

    try:
        # Swapping test
        test.log.info("Swapping test start")
        # Parameters of memory information
        # @total: Memory size - MemTotal
        # @free: Free memory size - MemFree
        # @swap_size: Swap size - SwapTotal
        # @swap_free: Free swap size - SwapFree
        # @hugepage_size: Page size of one hugepage - Hugepagesize
        mem_check_list = [
            "MemTotal",
            "MemFree",
            "SwapTotal",
            "SwapFree",
            "Hugepagesize",
        ]
        mem_info = get_mem_info(mem_check_list)
        total = mem_info["MemTotal"]
        free = mem_info["MemFree"]
        swap_size = mem_info["SwapTotal"]
        swap_free_initial = mem_info["SwapFree"]
        hugepage_size = mem_info["Hugepagesize"]
        login_timeout = params.get_numeric("login_timeout", 360)
        check_cmd_timeout = params.get_numeric("check_cmd_timeout", 900)
        mem_path = os.path.join(test.tmpdir, "thp_space")

        # If swap is enough fill all memory with dd
        if swap_free_initial > (total - free):
            tmpfs_size = total
        else:
            tmpfs_size = free

        if swap_size <= 0:
            test.log.warning("Host does not have swap enabled")
        session = None
        try:
            if not os.path.isdir(mem_path):
                os.makedirs(mem_path)
            process.run(
                "mount -t tmpfs  -o size=%sM none %s" % (tmpfs_size, mem_path),
                shell=True,
            )

            # Set the memory size of vm
            # To ignore the oom killer set it to the free swap size
            vm = env.get_vm(params.get("main_vm"))
            vm.verify_alive()
            if params.get_numeric("mem") > swap_free_initial:
                vm.destroy()
                vm_name = "vmsw"
                vm0 = params.get("main_vm")
                vm0_key = env.get_vm(vm0)
                params["vms"] = params["vms"] + " " + vm_name
                # For ppc, vm mem must align to 256MB, apply it for all arch
                params["mem"] = math.floor(swap_free_initial / 256) * 256
                vm_key = vm0_key.clone(vm0, params)
                env.register_vm(vm_name, vm_key)
                env_process.preprocess_vm(test, params, env, vm_name)
                session = vm_key.wait_for_login(timeout=login_timeout)
            else:
                session = vm.wait_for_login(timeout=login_timeout)

            error_context.context("Disable swap in the guest", test.log.info)
            s, o = session.cmd_status_output("swapoff -a")
            if s != 0:
                test.error("Disable swap in guest failed as %s" % o)

            error_context.context("making guest to swap memory", test.log.debug)
            free = mem_info["MemFree"]
            count = free // hugepage_size
            cmd = "dd if=/dev/zero of=%s/zero bs=%sM count=%s" % (
                mem_path,
                hugepage_size,
                count,
            )
            process.run(cmd, shell=True)

            mem_info = get_mem_info(mem_check_list)
            swap_free_after = mem_info["SwapFree"]
            error_context.context(
                "Swap after filling memory: %d" % swap_free_after, test.log.debug
            )

            if swap_free_after - swap_free_initial >= 0:
                test.fail("No data was swapped to memory")

            # Try harder to make guest memory to be swapped
            session.cmd(
                'find / -name "*"', timeout=check_cmd_timeout, ignore_all_errors=True
            )
        finally:
            if session is not None:
                process.run("umount %s" % mem_path, shell=True)

        test.log.info("Swapping test succeed")

    finally:
        if session is not None:
            session.close()
