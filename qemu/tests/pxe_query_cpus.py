import logging
import os
import time

import aexpect
from avocado.utils import process
from virttest import cpu, env_process, error_context, qemu_monitor, utils_misc, virt_vm

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def _capture_tftp(test, vm, timeout):
    error_context.context("Snoop packet in the tap device", LOG_JOB.info)
    output = aexpect.run_fg(
        "tcpdump -nli %s port '(tftp or bootps)'" % vm.get_ifname(),
        LOG_JOB.debug,
        "(pxe capture) ",
        timeout,
    )[1]

    error_context.context("Analyzing the tcpdump result", LOG_JOB.info)
    if "tftp" not in output:
        test.fail("Couldn't find any TFTP packets after %s seconds" % timeout)
    LOG_JOB.info("Found TFTP packet")


def _kill_vms(params, env):
    for vm in env.get_all_vms():
        if vm:
            vm.destroy()
            env.unregister_vm(vm.name)

    qemu_bin = os.path.basename(params["qemu_binary"])
    process.run("killall -g %s" % qemu_bin, ignore_status=True)
    time.sleep(5)


@error_context.context_aware
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
    restore_mmu_cmd = None
    pxe_timeout = int(params.get("pxe_timeout", 60))

    error_context.context("Enable ept/npt", test.log.info)
    try:
        flag = list(filter(lambda x: x in cpu.get_cpu_flags(), ["ept", "npt"]))[0]
    except IndexError:
        test.log.info("Host doesn't support ept/npt, skip the configuration")
    else:
        enable_mmu_cmd = params["enable_mmu_cmd_%s" % flag]
        check_mmu_cmd = params["check_mmu_cmd_%s" % flag]
        restore_mmu_cmd = params["restore_mmu_cmd_%s" % flag]
        status = process.system(
            check_mmu_cmd, timeout=120, ignore_status=True, shell=True
        )
        if status != 0:
            _kill_vms(params, env)
            process.run(enable_mmu_cmd, shell=True)

    params["start_vm"] = "yes"
    params["kvm_vm"] = "yes"
    params["paused_after_start_vm"] = "yes"

    error_context.context("Try to boot from NIC", test.log.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    bg = utils_misc.InterruptedThread(_capture_tftp, (test, vm, pxe_timeout))

    count = 0
    try:
        bg.start()
        error_context.context("Query cpus in loop", test.log.info)
        vm.resume()
        while True:
            count += 1
            try:
                vm.monitor.info("cpus", debug=False)
                if params.get("machine_type").startswith("s390"):
                    if vm.monitor.get_status()["status"] in [
                        "running",
                        "guest-panicked",
                    ]:
                        pass
                    else:
                        raise virt_vm.VMStatusError(
                            'Unexpected VM status: "%s"' % vm.monitor.get_status()
                        )
                else:
                    vm.verify_status("running")
                if not bg.is_alive():
                    break
            except qemu_monitor.MonitorSocketError:
                test.fail("Qemu looks abnormally, please read the log")
        test.log.info("Execute info/query cpus %d times", count)
    finally:
        bg.join()
        if restore_mmu_cmd:
            _kill_vms(params, env)
            process.run(restore_mmu_cmd, shell=True)
