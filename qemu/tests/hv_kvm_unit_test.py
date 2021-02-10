import logging
import re
import json

from virttest import error_context
from virttest import data_dir
from virttest import cpu
from avocado.utils import process


@error_context.context_aware
def run(test, params, env):
    """
    Run kvm-unit-tests for Hyper-V testdev device

    1) compile kvm-unit-tests tools source code
    2) Run each unit tests by compiled binary tools
    3) For each unit test, compare the test result to expected value
    """
    tmp_dir = data_dir.get_tmp_dir()
    kvm_unit_tests_dir = data_dir.get_deps_dir("kvm_unit_tests")
    compile_cmd = params["compile_cmd"] % (tmp_dir, kvm_unit_tests_dir)
    test_cmd = params["test_cmd"]
    unit_tests_mapping = params["unit_tests_mapping"]
    skip_tests = params.get("skip_tests", "").split()
    cpu_flags = params["cpu_model_flags"]
    cpu_model = cpu.get_qemu_best_cpu_model(params)
    cpu_param = cpu_model + cpu_flags

    error_context.context("Copy & compile kvm-unit-test tools", logging.info)
    process.system(compile_cmd, shell=True)

    error_context.context("Run unit tests", logging.info)
    for unit_test, unit_test_result in json.loads(unit_tests_mapping).items():
        if unit_test in skip_tests:
            continue
        logging.info("Start running unit test %s", unit_test)
        unit_test_cmd = test_cmd % (tmp_dir, unit_test, cpu_param)
        result_output = process.system_output(unit_test_cmd, shell=True)
        result_output = result_output.decode()
        find_result = re.findall('^%s' % unit_test_result[0], result_output, re.M)
        if len(find_result) != int(unit_test_result[1]):
            test.fail("Unit test result mismatch target, "
                      "target=%s, output=%s" %
                      (unit_test_result[1], result_output))
