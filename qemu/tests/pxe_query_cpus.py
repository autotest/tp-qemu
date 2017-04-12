import os
import time
import logging

from autotest.client.shared import error
from autotest.client.shared import utils

from virttest import utils_test
from virttest import utils_misc
from virttest import qemu_monitor
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    Qemu guest pxe boot test:
    1). check npt/ept function enable, then boot vm
    2). execute query/info cpus in loop
    3). verify vm not paused during pxe booting

    params:
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def stopVMS(params, env):
        """
        Kill all VMS for relaod kvm_intel/kvm_amd module;
        """
        for vm in env.get_all_vms():
            if vm:
                vm.destroy()
                env.unregister_vm(vm.name)

        qemu_bin = os.path.basename(params["qemu_binary"])
        utils.run("killall -g %s" % qemu_bin, ignore_status=True)
        time.sleep(5)

    enable_mmu_cmd = None
    check_mmu_cmd = None
    restore_mmu_cmd = None
    error.context("Enable ept(npt)", logging.info)
    try:
        flag = filter(lambda x: x in utils_misc.get_cpu_flags(),
                      ['ept', 'npt'])[0]
    except IndexError:
        logging.warn("Host doesn't support ept(npt)")
    else:
        enable_mmu_cmd = params["enable_mmu_cmd_%s" % flag]
        check_mmu_cmd = params["check_mmu_cmd_%s" % flag]
        status = utils.system(check_mmu_cmd, timeout=120, ignore_status=True)
        if status != 0:
            stopVMS(params, env)
            utils.run(enable_mmu_cmd)
            restore_mmu_cmd = params["restore_mmu_cmd_%s" % flag]

    params["start_vm"] = "yes"
    params["kvm_vm"] = "yes"
    params["paused_after_start_vm"] = "yes"

    env_process.preprocess_vm(test, params, env, params["main_vm"])
    bg = utils.InterruptedThread(utils_test.run_virt_sub_test,
                                 args=(test, params, env,),
                                 kwargs={"sub_type": "pxe_boot"})
    count = 0
    try:
        bg.start()
        error.context("Query cpus in loop", logging.info)
        vm = env.get_vm(params["main_vm"])
        vm.resume()
        while True:
            count += 1
            try:
                vm.monitor.info("cpus")
                vm.verify_status("running")
                if not bg.is_alive():
                    break
            except qemu_monitor.MonitorSocketError:
                raise error.TestFail("Qemu looks abnormally, please read the log")
        logging.info("Execute info/query cpus %d times", count)
    finally:
        bg.join()
        if restore_mmu_cmd:
            stopVMS(params, env)
            utils.run(restore_mmu_cmd)
