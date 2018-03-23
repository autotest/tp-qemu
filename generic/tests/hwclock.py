import re
import logging

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check hwclock can be set and read successfully.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=240)

    logging.info("Setting hwclock to 2/2/80 03:04:00")
    session.cmd('/sbin/hwclock --set --date "2/2/80 03:04:00"')
    date = session.cmd_output('LC_ALL=C /sbin/hwclock')
    if not re.match('Sat *Feb *2 *03:04:.. 1980', date):
        test.fail("Fail to set hwclock back to the 80s."
                  "Output of hwclock is '%s'" % date)
