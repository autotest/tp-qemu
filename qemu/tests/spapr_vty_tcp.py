import logging

from autotest.client.shared import error
from avocado.core import exceptions
from virttest.staging import utils_memory


@error.context_aware
def run(test, params, env):
    """
    KVM spapr-vty test on ppc host:
    1) Wait for the serial console
    2) Send 'ls' command via console
    3) Send 'pwd' command via console
    4) Send 'reboot' command via console

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    try:
        error.context("Login serial console via spapr-vty", logging.info)
        timeout = int(params["login_timeout"])
        session = vm.wait_for_serial_login(timeout=timeout)
        cmd_result = {
            "ls": "anaconda-ks.cfg",
            "pwd": "/root",
        }
        for key in cmd_result.keys():
            output = session.cmd_output(key)
            if cmd_result[key] not in output:
                error.context("cmd is %s but output don't include %s" %
                              (key, cmd_result[key]))
                raise exceptions.TestFail("spapr_vty_tcp basic test failed")

        error.context("Send a 'reboot' command to the guest", logging.info)
        utils_memory.drop_caches()
        session.cmd('reboot', timeout=1, ignore_all_errors=True)

    except Exception:
        raise exceptions.TestFail("spapr_vty_tcp test case failed")
