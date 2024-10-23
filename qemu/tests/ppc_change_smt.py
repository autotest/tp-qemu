import re
from math import log

from aexpect import ShellCmdError
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Change the guest smt state and check it's CPU information

    1) Launch a guest with specific threads
    2) Check if the number of threads on guest is equal to SMP threads
    3) Change the smt state and check if it matches the expected

    :param test: the test object
    :param params: the test params
    :param env: test environment
    """

    def _check_smt_state(value):
        value = "1" if value == "off" else str(threads) if value == "on" else value
        smt_info = session.cmd_output("ppc64_cpu --smt -n")
        if not re.match(r"SMT=%s" % value, smt_info):
            test.log.info("smt info of guest: %s", smt_info)
            test.fail("The smt state is inconsistent with expected")
        test.log.info("smt state matched: %s", value)

    def _change_smt_state(value):
        try:
            session.cmd("ppc64_cpu --smt=%s" % value)
            _check_smt_state(value)
        except ShellCmdError as err:
            test.log.error(str(err))
            test.error("Failed to change smt state of guest to %s." % value)

    def _smt_state(n_threads):
        for i in range(int(log(n_threads, 2)) + 1):
            yield str(pow(2, i))
        yield "off"
        yield "on"

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    threads = vm.cpuinfo.threads

    error_context.context(
        "Check if the number of threads on guest is equal to" " SMP threads",
        test.log.info,
    )
    _check_smt_state(threads)

    for state in _smt_state(threads):
        error_context.context(
            "Change the guest's smt state to %s" % state, test.log.info
        )
        _change_smt_state(state)
        cpu_count = threads if state == "on" else 1 if state == "off" else int(state)
        error_context.context(
            "Check if the online CPU per core is equal to %s" % cpu_count, test.log.info
        )
        for core_info in session.cmd_output("ppc64_cpu --info").splitlines():
            if cpu_count != core_info.count("*"):
                test.log.info("core_info:\n%s", core_info)
                test.fail("cpu info is incorrect after changing smt state")
