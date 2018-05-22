import logging
import re

from virttest import error_context
from virttest import utils_test
from virttest import utils_misc


def get_mq_from_guest(session, params, cmd, pattern):
    """
    Get multi queue number from guest.

    :param session: VM session
    :param params: Dictionary with the test parameters
    :param cmd: command to get queue info
    :param pattern: Get the queue number from queue info
    """
    status, output = session.cmd_status_output(cmd)
    if status != 0:
        return output
    if params.get("os_type") == "windows":
        try:
            queues = int(re.search(pattern, output, re.I | re.M).group(1))
        except IndexError:
            return None
    if params.get("os_type") == "linux":
        queues = int(len(re.findall(pattern, output, re.I | re.M)))
    if queues:
        return queues
    else:
        return None


@error_context.context_aware
def run(test, params, env):
    """
    Check device multi-queue function enabled.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    driver_name = params["driver_name"]
    session = vm.wait_for_login(timeout=timeout)
    num_queues = params["num_queues"]
    pattern = params["pattern"]
    check_queue_cmd = params["check_queue_cmd"]

    try:
        if params.get("os_type") == "windows" and driver_name:
            session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                    test, driver_name,
                                                                    timeout)
            check_queue_cmd = utils_misc.set_winutils_letter(session, check_queue_cmd)
        error_context.context("Get the num_queues info", logging.info)
        result_guest = get_mq_from_guest(session, params, check_queue_cmd, pattern)
        if not isinstance(result_guest, int):
            test.error("Get multi queue info failed, check the detail result:\n%s"
                       % result_guest)
        if result_guest == int(num_queues):
            error_context.context("The num_queues from guest is match with expected",
                                  logging.info)
        else:
            test.fail("The num_queues from guest is not match with expected.\n"
                      "num_queues from guest is %s, expected is %s"
                      % (result_guest, num_queues))
    finally:
        session.close()
