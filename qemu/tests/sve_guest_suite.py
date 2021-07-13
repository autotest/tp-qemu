import re
import logging

from virttest import error_context
from virttest import utils_package

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def get_sve_supports_lengths():
        """
        Get supported SVE lengths of host.
        """
        output = vm.monitor.query_cpu_model_expansion(vm.cpuinfo.model)
        output.pop('sve')
        sve_list = [sve for sve in output if output[sve] is True and
                    sve.startswith('sve')]
        sve_list.sort(key=lambda x: int(x[3:]))
        return sve_list

    def compile_test_suite():
        error_context.context('Compose the test suite......', logging.info)
        git_cmd = 'git clone --depth=1 {} {} 2>/dev/null'.format(git_repo,
                                                                 dst_dir)
        session.cmd(git_cmd, timeout=180)
        session.cmd(compile_cmd, timeout=180)

    def sve_stress():
        s, o = session.cmd_status_output('./sve-probe-vls')
        test_lengths = re.findall(r'# (\d+)$', o, re.M)
        if s or not test_lengths:
            test.error('Could not get supported SVE lengths by "sve-probe-vls"')
        logging.info('The lengths of SVE used for testing are: %s', test_lengths)
        for sve_length in test_lengths:
            out = session.cmd_output(execute_suite_cmd.format(sve_length),
                                     timeout=(suite_timeout + 10))
            results_lines = [result for result in out.splitlines() if
                             result.startswith('Terminated by')]
            if len(re.findall(r'no error', out, re.M)) != len(results_lines):
                logging.debug('Test results: %s', results_lines)
                test.fail('SVE stress test failed')

    def optimized_routines():
        out = session.cmd_output(execute_suite_cmd, timeout=suite_timeout)
        results = re.findall(r'^(\w+) \w+sve$', out, re.M)
        if not all([result == "PASS" for result in results]):
            logging.debug('Test results: %s', results)
            test.fail('optimized routines suite test failed')

    cpu_utils.check_cpu_flags(params, 'sve', test)
    vm = env.get_vm(params["main_vm"])
    sve_lengths = get_sve_supports_lengths()
    vm.destroy()

    dst_dir = params['dst_dir']
    git_repo = params['git_repo']
    suite_type = params['suite_type']
    compile_cmd = params['compile_cmd']
    suite_timeout = params.get_numeric('suite_timeout')
    required_pkgs = params.objects('required_pkgs')
    execute_suite_cmd = params['execute_suite_cmd']

    error_context.context('Launch a guest with sve=on', logging.info)
    sve_opts = ('{}={}'.format(sve, 'on') for sve in sve_lengths)
    params['cpu_model_flags'] = 'sve=on,' + ','.join(sve_opts)
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()
    cpu_utils.check_cpu_flags(params, 'sve', test, session)

    if not utils_package.package_install(required_pkgs, session):
        test.error("Failed to install required packages in guest")
    compile_test_suite()
    error_context.context('Execute the test suite......', logging.info)
    locals()[suite_type]()
