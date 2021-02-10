import re
import os
import time
import logging

from shutil import copyfile

from avocado.utils import process

from virttest import arch
from virttest import env_process
from virttest import utils_misc
from virttest.utils_test import VMStress
from virttest.staging import utils_memory


def run(test, params, env):
    """
    Check KSM can be started automaticly when ksmtuned threshold is reached

    1. Get the memory of your host and the KSM_THRES_COEF
    2. Boot a guest with memory less than KSM_THRES_COEF threshold
    3. Get the memory used in host of process qemu-kvm
    4. Get the free memory in host
    5. If both the free memory size is not smaller than the threshold and guest
        used memory + threshold is not bigger than total memory in host. Check
        the ksm status in host. Ksm should not start in the host
    6. Repeat step 2~5 under it broke the rule in step 5

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def check_ksm(mem, stress=False):
        """
        :param mem: Boot guest with given memory, in KB
        :param stress: Load stress or not
        """
        params['mem'] = mem // 1024
        params['start_vm'] = 'yes'
        vm_name = params['main_vm']
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.wait_for_login()
        if stress:
            params['stress_args'] = ('--cpu 4 --io 4 --vm 2 --vm-bytes %sM' %
                                     (int(params['mem']) // 2))
            stress_test = VMStress(vm, "stress", params)
            stress_test.load_stress_tool()
            time.sleep(30)
        qemu_pid = vm.get_pid()
        qemu_used_page = utils_misc.normalize_data_size(process.getoutput(
            params['cmd_get_qemu_used_mem'] % qemu_pid, shell=True) + 'K', 'B')
        pagesize = utils_memory.getpagesize()
        qemu_used_mem = int(float(qemu_used_page)) * pagesize
        free_mem_host = utils_memory.freememtotal()
        ksm_status = process.getoutput(params['cmd_check_ksm_status'])
        vm.destroy()
        logging.info('The ksm threshold is %s, the memory allocated by qemu is'
                     ' %s, and the total free memory on host is %s.',
                     ksm_thres, qemu_used_mem, free_mem_host)
        if free_mem_host >= ksm_thres:
            if ksm_status != '0':
                test.fail('Ksm should not start.')
            if stress:
                test.error('The host resource is not consumed as expected.')
        elif ksm_status == '0':
            test.fail('Ksm should start but it does not.')

    total_mem_host = utils_memory.memtotal()
    utils_memory.drop_caches()
    free_mem_host = utils_memory.freememtotal()
    ksm_thres = process.getoutput(params['cmd_get_thres'], shell=True)
    ksm_thres = int(total_mem_host *
                    (int(re.findall('\\d+', ksm_thres)[0]) / 100))
    guest_mem = (free_mem_host - ksm_thres) // 2
    if arch.ARCH in ('ppc64', 'ppc64le'):
        guest_mem = guest_mem - guest_mem % (256 * 1024)
    status_ksm_service = process.system(
        params['cmd_status_ksmtuned'], ignore_status=True)
    if status_ksm_service != 0:
        process.run(params['cmd_start_ksmtuned'])
    check_ksm(guest_mem)

    ksm_config_file = params['ksm_config_file']
    backup_file = ksm_config_file + '.backup'
    copyfile(ksm_config_file, backup_file)
    threshold = params.get_numeric('ksm_threshold')
    with open(ksm_config_file, "a+") as f:
        f.write('%s=%s' % (params['ksm_thres_conf'], threshold))
    process.run(params['cmd_restart_ksmtuned'])
    ksm_thres = total_mem_host * (threshold / 100)
    guest_mem = total_mem_host - ksm_thres // 2
    if arch.ARCH in ('ppc64', 'ppc64le'):
        guest_mem = guest_mem - guest_mem % (256 * 1024)
    try:
        check_ksm(guest_mem, stress=True)
    finally:
        copyfile(backup_file, ksm_config_file)
        os.remove(backup_file)
        if status_ksm_service != 0:
            process.run(params['cmd_stop_ksmtuned'])
        else:
            process.run(params['cmd_restart_ksmtuned'])
