import time
import os
import re

from avocado.utils import process
from virttest import test_setup
from virttest import error_context
from virttest import kernel_interface


@error_context.context_aware
def run(test, params, env):
    """
    KVM khugepage userspace side test:
    1) Verify that the host supports kernel hugepages.
        If it does proceed with the test.
    2) Verify that the kernel hugepages can be used in host.
    3) Verify that the kernel hugepages can be used in guest.
    4) Use dd and tmpfs to make fragement in memory
    5) Use libhugetlbfs to allocated huge page before start defrag
    6) Set the khugepaged do defrag
    7) Use libhugetlbfs to allocated huge page compare the value

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def get_mem_stat(param):
        """
        Get the memory size for a given memory param.

        :param param: Memory parameter.
        """
        with open('/proc/meminfo', 'r') as f:
            for line in f.readlines():
                if line.startswith("%s" % param):
                    output = re.split(r'\s+', line)[1]
            return int(output)

    def set_libhugetlbfs(number):
        """
        Set the number of hugepages on the system.

        :param number: Number of pages (either string or numeric).
        """
        test.log.info("Trying to setup %d hugepages on host", number)
        nr_hugepages = kernel_interface.ProcFS('/proc/sys/vm/nr_hugepages', session=None)
        pre_ret = nr_hugepages.proc_fs_value
        test.log.debug("Number of huge pages on libhugetlbfs"
                       " (pre-write): %s", pre_ret)
        nr_hugepages.proc_fs_value = int(number)
        ret = nr_hugepages.proc_fs_value
        test.log.debug("Number of huge pages on libhugetlbfs:"
                       " (post-write): %s", ret)
        return int(ret)

    def change_feature_status(test, status, feature_path, test_config):
        """
        Turn on/off feature functionality.

        :param status: String representing status, may be 'on' or 'off'.
        :param relative_path: Path of the feature relative to THP config base.
        :param test_config: Object that keeps track of THP config state.

        :raise: error.TestFail, if can't change feature status
        """

        thp = kernel_interface.SysFS(os.path.join(test_config.thp_path, feature_path), session=None)
        possible_values = [each.strip("[]") for each in thp.fs_value.split()]

        if 'yes' in possible_values:
            on_action = 'yes'
            off_action = 'no'
        elif 'always' in possible_values:
            on_action = 'always'
            off_action = 'never'
        elif '1' in possible_values or '0' in possible_values:
            on_action = '1'
            off_action = '0'
        else:
            raise ValueError("Uknown possible values for file %s: %s" %
                             (test_config.thp_path, possible_values))

        if status == 'on':
            action = on_action
        elif status == 'off':
            action = off_action

        thp.sys_fs_value = action
        time.sleep(1)

    def fragment_host_memory(mem_path):
        """
        Attempt to fragment host memory.

        It accomplishes that goal by spawning a large number of dd processes
        on a tmpfs mount.

        :param mem_path: tmpfs mount point.
        """
        error_context.context("Fragmenting host memory")
        try:
            test.log.info("Prepare tmpfs in host")
            if not os.path.isdir(mem_path):
                os.makedirs(mem_path)
            process.run("mount -t tmpfs none %s" % mem_path, shell=True)
            test.log.info("Start using dd to fragment memory in guest")
            cmd = ("for i in `seq 262144`; do dd if=/dev/urandom of=%s/$i "
                   "bs=4K count=1 & done" % mem_path)
            process.run(cmd, shell=True)
        finally:
            process.run("umount %s" % mem_path, shell=True)

    test_config = test_setup.TransparentHugePageConfig(test, params, env)
    test.log.info("Defrag test start")
    login_timeout = float(params.get("login_timeout", 360))
    mem_path = os.path.join("/tmp", "thp_space")

    try:
        error_context.context("deactivating khugepaged defrag functionality")
        change_feature_status(test, "off", "khugepaged/defrag", test_config)
        change_feature_status(test, "off", "defrag", test_config)

        vm = env.get_vm(params.get("main_vm"))
        session = vm.wait_for_login(timeout=login_timeout)

        fragment_host_memory(mem_path)

        total = get_mem_stat('MemTotal')
        hugepagesize = get_mem_stat('Hugepagesize')
        nr_full = int(0.8 * (total / hugepagesize))

        nr_hp_before = set_libhugetlbfs(nr_full)

        error_context.context("activating khugepaged defrag functionality")
        change_feature_status(test, "on", "khugepaged/defrag", test_config)
        change_feature_status(test, "on", "defrag", test_config)

        sleep_time = 10
        test.log.debug("Sleeping %s s to settle things out", sleep_time)
        time.sleep(sleep_time)

        nr_hp_after = set_libhugetlbfs(nr_full)

        if nr_hp_before >= nr_hp_after:
            test.fail("No memory defragmentation on host: "
                      "%s huge pages before turning "
                      "khugepaged defrag on, %s after it" %
                      (nr_hp_before, nr_hp_after))
        test.log.info("Defrag test succeeded")
        session.close()
    finally:
        test.log.debug("Cleaning up libhugetlbfs on host")
        set_libhugetlbfs(0)
