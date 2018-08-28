import logging

from avocado.utils import process, path
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Run tracing of exception injection test

    1) Boot the main vm, or just verify it if it's already booted.
    2) In host run kvm_stat, it should work.
    3) In host check host allow tracing of exception injection in KVM.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error_context.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Check that kvm_stat works in host", logging.info)
    kvm_stat_bin = path.find_command("kvm_stat")
    check_cmd = "%s -1 -f exits" % kvm_stat_bin
    host_cmd_output = process.system_output(check_cmd)
    if host_cmd_output:
        if host_cmd_output.split()[1] == '0':
            test.fail("kvm_stat did not provide the expected "
                      "output: %s" % host_cmd_output)
        logging.info("kvm_stat provided the expected output")
    logging.info("Host cmd output '%s'", host_cmd_output)

    error_context.context(
        "Check that host allows tracing of exception injection in KVM",
        logging.info)
    exec_cmd = "grep kvm:kvm_inj_exception "
    exec_cmd += " /sys/kernel/debug/tracing/available_events"
    inj_check_cmd = params.get("injection_check_cmd", exec_cmd)
    try:
        process.run(inj_check_cmd, shell=True)
    except process.CmdError:
        err_msg = "kvm:kvm_inj_exception is not an available event in host"
        test.fail(err_msg)
    logging.info("Host supports tracing of exception injection in KVM")
