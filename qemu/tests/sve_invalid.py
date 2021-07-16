import re
import logging

from virttest import error_context
from virttest.virt_vm import VMCreateError

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def get_sve_unsupported_lengths():
        """
        Get unsupported SVE lengths of host.
        """
        output = vm.monitor.query_cpu_model_expansion(vm.cpuinfo.model)
        output.pop('sve')
        sve_list = [sve for sve in output if output[sve] is False and
                    sve.startswith('sve')]
        sve_list.sort(key=lambda x: int(x[3:]))

        return sve_list

    error_msg = params['error_msg']
    invalid_length = params.get('invalid_length')

    cpu_utils.check_cpu_flags(params, 'sve', test)

    vm = env.get_vm(params["main_vm"])
    if not invalid_length:
        sve_lengths = get_sve_unsupported_lengths()
        invalid_length = sve_lengths[-1]
        error_msg = error_msg.format(invalid_length[3:])
        vm.destroy()
        params['cpu_model_flags'] = 'sve=on,{}=on'.format(invalid_length)

    params['start_vm'] = 'yes'
    try:
        error_context.context('Launch a guest with invalid SVE length',
                              logging.info)
        vm.create(params=params)
    except VMCreateError as err:
        if not re.search(error_msg, err.output, re.M):
            test.error('The guest failed to be launched but did not get the '
                       'expected error message.')
        logging.info('The qemu process terminated as expected.')
    else:
        test.fail('The guest should not be launched.')
