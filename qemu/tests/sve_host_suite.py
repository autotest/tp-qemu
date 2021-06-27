import os
import re
import shutil
import logging

from avocado.utils import process

from virttest import error_context
from virttest import utils_package

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def compile_kernel_selftests():
        git_cmd = 'git clone --depth=1 {} {} 2>/dev/null'.format(git_repo,
                                                                 dst_dir)
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)
        process.run(git_cmd, timeout=360, shell=True)
        s, o = process.getstatusoutput(compile_cmd, timeout=180)
        if s:
            logging.error('Compile output: %s', o)
            test.error('Failed to compile the test suite.')

    dst_dir = params['dst_dir']
    git_repo = params['git_repo']
    compile_cmd = params['compile_cmd']
    execute_suite_cmd = params['execute_suite_cmd']
    required_pkgs = params.objects('required_pkgs')
    suite_timeout = params.get_numeric('suite_timeout')

    if not utils_package.package_install(required_pkgs):
        test.error("Failed to install required packages in host")
    error_context.base_context('Check if the CPU of host supports SVE',
                               logging.info)
    cpu_utils.check_cpu_flags(params, 'sve', test)

    try:
        compile_kernel_selftests()
        s, o = process.getstatusoutput(execute_suite_cmd, timeout=suite_timeout)
        if s:
            test.fail('The exit code of "get-reg-list" test suite is not 0.')
        elif not all([result == "PASS" for result in
                      re.findall(r'^sve\S*: (\w+)$', o, re.M)]):
            logging.error('Test result: %s', o)
            test.fail('The sve part of the "get-reg-list" test failed')
        logging.info('get-reg-list test passed')
    finally:
        shutil.rmtree(dst_dir, ignore_errors=True)
