import re
import logging

from avocado.utils import process

from virttest import cpu
from virttest import error_context
from virttest import utils_qemu
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Runs CPU negative test:

    1. Launch qemu with improper cpu configuration
    2. Verify qemu failed to start

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    enforce_flag = params.get('enforce_flag')
    if enforce_flag and 'CPU_MODEL' in params['wrong_cmd']:
        if enforce_flag in cpu.get_host_cpu_models():
            test.cancel('This case only test on the host without the flag'
                        ' %s.' % enforce_flag)
        cpu_model = cpu.get_qemu_best_cpu_model(params)
        params['wrong_cmd'] = params['wrong_cmd'].replace('CPU_MODEL',
                                                          cpu_model)

    qemu_bin = utils_misc.get_qemu_binary(params)
    if 'OUT_OF_RANGE' in params['wrong_cmd']:
        machine_type = params['machine_type'].split(':')[-1]
        m_types = utils_qemu.get_machines_info(qemu_bin)[machine_type]
        m_type = re.search(r'\(alias of (\S+)\)', m_types)[1]
        max_value = utils_qemu.get_maxcpus_hard_limit(qemu_bin, m_type)
        smp = str(max_value + 1)
        params['wrong_cmd'] = params['wrong_cmd'].replace(
            'MACHINE_TYPE', machine_type).replace('OUT_OF_RANGE', smp)
        msg = params['warning_msg'].replace('SMP_VALUE', smp).replace(
            'MAX_VALUE', str(max_value)).replace('MACHINE_TYPE', m_type)
        params['warning_msg'] = msg

    warning_msg = params['warning_msg']
    wrong_cmd = '%s %s' % (qemu_bin, params['wrong_cmd'])
    logging.info('Start qemu with command: %s', wrong_cmd)
    status, output = process.getstatusoutput(wrong_cmd)
    logging.info('Qemu prompt output:\n%s', output)
    if status == 0:
        test.fail('Qemu guest boots up while it should not.')
    if warning_msg not in output:
        test.fail('Does not get expected warning message.')
    else:
        logging.info('Test passed as qemu does not boot up and'
                     ' prompts expected message.')
