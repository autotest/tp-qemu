"""
slof_hugepage.py include following case:
 1. Boot guest with hugepage backing file then hotplug hugepage.
 2. Boot guest without hugepage backing file then hotplug hugepage.
"""

import logging

from virttest import (
    env_process,
    error_context,
    test_setup,
    utils_misc,
    utils_net,
    utils_numeric,
)
from virttest.utils_test.qemu import MemoryHotplugTest

from provider import slof

LOG_JOB = logging.getLogger("avocado.test")


def _setup_hugepage(params):
    """
    Setup the configure of host:
     1. Check the size of hugepage on host.
     2. Calculate the num of assigning pages by (assigning total size /
        hugepage size).
     3. Set hugepage by executing "echo $num > /proc/sys/vm/nr_hugepages".
     4. Mount this hugepage to /mnt/kvm_hugepage.
    """
    size = params["total_hugepage_size"]
    huge_page = test_setup.HugePageConfig(params)
    error_context.context("Assign %sMB hugepages in host." % size, LOG_JOB.info)

    hugepage_size = huge_page.get_hugepage_size()
    LOG_JOB.debug("Hugepage size is %skB in host.", hugepage_size)

    huge_page.target_hugepages = int((int(size) * 1024) // hugepage_size)
    LOG_JOB.debug("Set hugepages to %d pages in host.", huge_page.target_hugepages)
    huge_page.set_node_num_huge_pages(huge_page.target_hugepages, 0, hugepage_size)

    error_context.context(
        "mount hugepages to %s" % huge_page.hugepage_path, LOG_JOB.info
    )
    huge_page.mount_hugepage_fs()
    params["hugepage_path"] = huge_page.hugepage_path


def _check_mem_increase(session, params, orig_mem):
    """Check the size of memory increased."""
    increase_mem = int(utils_numeric.normalize_data_size(params["size_mem_plug"], "B"))
    new_mem = int(session.cmd_output(cmd=params["free_mem_cmd"]))
    if (new_mem - orig_mem) == increase_mem:
        error_context.context(
            "Get guest free memory size after hotplug pc-dimm.", LOG_JOB.info
        )
        LOG_JOB.debug("Guest free memory size is %d bytes", new_mem)
        LOG_JOB.info("Guest memory size is increased %s.", params["size_mem_plug"])
        return True
    return False


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info with hugepage.

    Step:
     1. Assign definite size hugepage and mount it in host.
     2. Boot a guest by following ways:
         a. hugepage as backing file
         b. hugepage not as backing file
        then Check if any error info in output of SLOF.
     3. Get the size of memory inside guest.
     4. Hot plug pc-dimm by QMP.
     5. Get the size of memory after hot plug pc-dimm inside guest,
        then check the different value of memory.
     6. Reboot guest.
     7. Guest could login successfully.
     8. Guest could ping external host ip.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _wait_for_login(cur_pos=0):
        """Wait for login guest."""
        content, next_pos = slof.wait_for_loaded(vm, test, cur_pos)
        error_context.context("Check the output of SLOF.", test.log.info)
        slof.check_error(test, content)

        error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
        timeout = float(params.get("login_timeout", 240))
        session = vm.wait_for_login(timeout=timeout)
        test.log.info("log into guest '%s' successfully.", vm.name)
        return session, next_pos

    _setup_hugepage(params)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session, next_pos = _wait_for_login()

    error_context.context(
        "Get guest free memory size before hotplug pc-dimm.", test.log.info
    )
    orig_mem = int(session.cmd_output(cmd=params["free_mem_cmd"]))
    test.log.debug("Guest free memory size is %d bytes", orig_mem)

    error_context.context("Hotplug pc-dimm for guest.", test.log.info)
    htp_mem = MemoryHotplugTest(test, params, env)
    htp_mem.hotplug_memory(vm, params["plug_mem_name"])

    plug_timeout = float(params.get("plug_timeout", 5))
    if not utils_misc.wait_for(
        lambda: _check_mem_increase(session, params, orig_mem), plug_timeout
    ):
        test.fail(
            "Guest memory size is not increased %s in %s sec."
            % (params["size_mem_plug"], params.get("plug_timeout", 5))
        )

    error_context.context("Reboot guest", test.log.info)
    session.close()
    vm.reboot()

    session, _ = _wait_for_login(next_pos)
    error_context.context("Try to ping external host.", test.log.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    session.cmd("ping %s -c 5" % extra_host_ip)
    test.log.info("Ping host(%s) successfully.", extra_host_ip)

    session.close()
    vm.destroy(gracefully=True)
