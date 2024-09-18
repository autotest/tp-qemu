import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Simply stop updates services in Windows guests.

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
        session.cmd("sc config %s start= disabled" % scname)
        output = session.cmd("sc qc %s" % scname)
        return re.search("disabled", output, re.M | re.I)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=float(params.get("login_timeout", 240)))

    cmd_timeout = float(params.get("cmd_timeout", 180))
    scname = params.get("win_update_service", "WuAuServ")

    error_context.context("Turned off windows updates service.", test.log.info)
    try:
        status = utils_misc.wait_for(
            lambda: disable_win_service(session, scname), timeout=cmd_timeout
        )
        if not status:
            test.fail("Turn off updates service failed.")
        session = vm.reboot(session)
    finally:
        session.close()
