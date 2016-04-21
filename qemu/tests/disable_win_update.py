import re
import logging
from virttest import utils_misc

# Make it work under both autotest-framework and avocado-framework
try:
    from avocado.core import exceptions
except ImportError:
    from autotest.client.shared import error as exceptions

try:
    from virttest import error_context
except ImportError:
    from autotest.client.shared import error as error_context


@error_context.context_aware
def run(test, params, env):
    """
    This simply stop updates services in Windows guests.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def disable_win_service(session, scname):
        """
        :param session: VM session.
        :param scname: Service name.

        :return: return True if scname has been disabled.
        """
        session.sendline("sc config %s start= disabled" % scname)
        output = session.cmd("sc qc %s" % scname)
        return re.search("disabled", output, re.M | re.I)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(
        timeout=float(params.get("login_timeout", 240)))

    cmd_timeout = float(params.get("cmd_timeout", 180))
    scname = params.get("win_update_service", "WuAuServ")

    error_context.context("Turned off windows updates service.",
                          logging.info)
    try:
        status = utils_misc.wait_for(lambda: disable_win_service(session, scname),
                                     timeout=cmd_timeout)
        if not status:
            raise exceptions.TestFail("Turn off updates service failed.")
        session = vm.reboot(session)
    finally:
        session.close()
