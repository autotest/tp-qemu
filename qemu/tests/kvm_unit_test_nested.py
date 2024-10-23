import os

from avocado.utils import process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run nested relstead tests in kvm-unit-test test suite

    1) Start multiple(4) L1 guest vms
    2) Clone kvm-unit-tests test suite from repo
    3) Compile test suite
    4) Run vmx/svm test suite with multiple running vms on host
    """

    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()

    kvm_unit_test_dir = os.path.join(test.logdir, "kvm_unit_tests/")
    test.log.info("kvm_unit_test_dir: %s", kvm_unit_test_dir)
    clone_cmd = params["clone_cmd"] % kvm_unit_test_dir
    process.system(clone_cmd)
    compile_cmd = params["compile_cmd"] % kvm_unit_test_dir
    process.system(compile_cmd, shell=True)

    error_context.context("Run kvm_unit_tests on host", test.log.info)
    timeout = params.get_numeric("kvm_unit_test_timeout", 60)
    run_cmd = params["test_cmd"] % kvm_unit_test_dir
    test.log.info("Run command %s ", run_cmd)
    status, output = process.getstatusoutput(run_cmd, timeout)

    if output:
        test.fail("kvm_unit_tests failed, status: %s, output: %s" % (status, output))
