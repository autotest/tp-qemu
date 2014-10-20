import logging
from autotest.client.shared import error
from virttest import utils_test
from autotest.client import utils


@error.context_aware
def run(test, params, env):
    """
    Qemu combine test:

    Reuse exist simple tests to combine a more complex
    scenario. Also support to run some simple command
    in guests and host.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def exe_cmd_in_guests(subtest_tag):
        timeout = int(params.get("login_timeout", 240))
        vms = env.get_all_vms()
        for vm in vms:
            params_vm = params.object_params(vm.name)
            params_vm_subtest = params_vm.object_params(subtest_tag)
            if params_vm_subtest.get('cmd'):
                error.context("Try to log into guest '%s'." % vm.name,
                              logging.info)
                session = vm.wait_for_login(timeout=timeout)
                cmd_timeout = int(params_vm_subtest.get("cmd_timeout", 240))
                cmd = params_vm_subtest['cmd']
                session.cmd(cmd, timeout=cmd_timeout)

    def exe_cmd_in_host(subtest_tag):
        params_subtest = params.object_params(subtest_tag)
        cmd_timeout = int(params_subtest.get("cmd_timeout", 240))
        cmd = params_subtest['cmd']
        utils.system(cmd, timeout=cmd_timeout)

    subtests = params["subtests"].split()

    for subtest in subtests:
        params_subtest = params.object_params(subtest)
        error.context("Run test %s" % subtest, logging.info)
        if params_subtest.get("subtest_type") == "guests":
            exe_cmd_in_guests(subtest)
        elif params_subtest.get("subtest_type") == "host":
            exe_cmd_in_host(subtest)
        else:
            utils_test.run_virt_sub_test(test, params, env, subtest, subtest)

        if params_subtest.get("check_vm_status_after_test", "yes") == "yes":
            vms = env.get_all_vms()
            for vm in vms:
                error.context("Check %s status" % vm.name, logging.info)
                vm.verify_userspace_crash()
                vm.verify_kernel_crash()
                vm.verify_kvm_internal_error()
