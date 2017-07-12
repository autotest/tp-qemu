import logging
import time

from virttest import utils_test
from virttest import error_context
from autotest.client.shared import utils
from autotest.client.shared import error


@error_context.context_aware
def run(test, params, env):
    """
    Compare host used memory after guest boot/reboot/shutdown for times:
    1) boot guest
    2) after guest up, check qemu memory utilization
    3) reboot guest for times
    4) check qemu memory utilization

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def mem_utilization(timeout):
        cmd = params.get("host_mem")
        qemu_mem = float(utils.system_output(cmd))
        end_time = time.time() + float(timeout)
        while time.time() < end_time:
            time.sleep(10)
            cur_qemu_mem = float(utils.system_output(cmd))
            if qemu_mem == cur_qemu_mem:
                return qemu_mem
            qemu_mem = cur_qemu_mem
        else:
            raise error.TestFail("Fail to get qemu_mem_utilization")

    timeout = params.get("login_timeout", 120)
    error_context.context("Check qemu memory utilization before test", logging.info)
    qemu_mem_utilization_before = mem_utilization(timeout)

    sub_test = params.get("sub_test")
    vm = env.get_vm(params["main_vm"])
    error_context.context("Do subtest:%s repeatly" % sub_test, logging.info)
    utils_test.run_virt_sub_test(test, params, env, sub_test)
    if not vm.is_alive():
        raise error.TestFail("Guest is dead during reboot test")

    error_context.context("Check qemu memory utilization after test", logging.info)
    qemu_mem_utilization_after = mem_utilization(timeout)

    error_context.context("Compare qemu's mem utilization", logging.info)
    if abs(qemu_mem_utilization_after - qemu_mem_utilization_before) > 1:
        raise error.TestFail("Host Memory Leak exist, please check")
