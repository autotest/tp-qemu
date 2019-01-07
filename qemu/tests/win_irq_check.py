import logging
import re
import ctypes

from virttest import error_context
from virttest import utils_test
from virttest import utils_misc
from provider import win_dev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU windows guest vitio device irq check test

    1) Start guest with virtio device.
    2) Make sure driver verifier enabled in guest.
    3) Get irq info in guest and check the value of irq number.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def irq_check(session, device_name, devcon_folder, timeout):
        """
        Check virtio device's irq number, irq number should be greater than zero.

        :param session: use for sending cmd
        :param device_name: name of the specified device
        :param devcon_folder: Full path for devcon.exe
        :param timeout: Timeout in seconds.
        """
        hwids = win_dev.get_hwids(session, device_name, devcon_folder, timeout)
        if not hwids:
            test.error("Didn't find %s device info from guest" % device_name)
        for hwid in hwids:
            get_irq_cmd = '%sdevcon.exe resources @"%s" | find "IRQ"' % (devcon_folder,
                                                                         hwid)
            output = session.cmd_output(get_irq_cmd)
            irq_value = re.split(r':+', output)[1]
            if ctypes.c_int32(int(irq_value)).value < 0:
                test.fail("%s's irq is not correct." % device_name, logging.info)

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
    devcon_folder = utils_misc.set_winutils_letter(session, params["devcon_folder"])
    irq_check(session, device_name, devcon_folder, timeout)

    if session:
        session.close()
