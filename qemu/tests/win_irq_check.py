import logging
import re

from virttest import error_context
from virttest import utils_test


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU windows guest vitio device irq check test

    1) Start guest with virtio device.
    2) Make sure driver verifier enabled in guest.
    3) Get irq info in guest.
    4) Check the value of irq number.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def irq_check(session, device_name):
        """
        Return virtio device's irq number
        :param session: use for sending cmd
        :param device_name: virtio device's name
        :param driver_name: virtio driver's name
        """
        status, irq_dev_info = session.cmd_status_output(params["irq_cmd"]
                                                         % device_name)
        if status:
            test.fail("Can't get %s's irq info." % device_name)
        irq_value = re.split(r'\s+', irq_dev_info)[1]
        logging.info("irq number is %s" % irq_value)
        return int(irq_value)

    driver = params["driver_name"]
    device_name = params["device_name"]
    timeout = int(params.get("login_timeout", 360))
    error_context.context("Boot guest with %s device" % driver, logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                            test, driver,
                                                            timeout)

    error_context.context("Check %s's irq number" % device_name, logging.info)
    irq_num = irq_check(session, device_name)
    if irq_num < 0:
        test.fail("%s's irq is not correct." % device_name,
                  logging.info)
    if session:
        session.close()
