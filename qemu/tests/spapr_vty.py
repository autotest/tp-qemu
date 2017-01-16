import logging

from autotest.client.shared import error
from avocado.core import exceptions


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

    def check_basic_cmd(session, op_type):
        cmd_result = {
            "ls": "anaconda-ks.cfg",
            "pwd": "/root",
        }
        for key in cmd_result.keys():
            output = session.cmd_output(key)
            if cmd_result[key] not in output:
                error.context("cmd is %s but output don't include %s" %
                              (key, cmd_result[key]))
                raise exceptions.TestFail("spapr_vty_%s basic test failed"
                                          % op_type)

    def check_reboot_cmd(session, cmd):
        error.context("Send a '%s' command to the guest" %
                      cmd, logging.info)
        session.cmd(cmd, timeout=1, ignore_all_errors=True)
    try:
        error.context("Get the main VM", logging.info)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        error.context("Login serial console via spapr-vty", logging.info)
        timeout = int(params["login_timeout"])
        session = vm.wait_for_serial_login(timeout=timeout)
        if not session:
            raise error.TestError("Login guest is timeout")
        op_type = params.get('serial_sockproto')
        if not op_type:
            raise error.TestError("Please define the backend beforehand")
        error.context("OP_TYPE is %s" % op_type, logging.info)
        check_basic_cmd(session, op_type)
        check_reboot_cmd(session, "reboot")
    except Exception:
        raise exceptions.TestFail("spapr_vty_%s test case failed" % op_type)
