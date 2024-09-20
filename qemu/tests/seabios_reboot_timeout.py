import re

from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM seabios test:
    1) Start VM
    2) Check if reboot-timeout option works as expected

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_output(session_obj):
        """
        Use the function to short the lines in the scripts
        """
        return session_obj.get_stripped_output()

    def reboot_timeout_check():
        """
        reboot-timeout check
        """
        return re.search(pattern, get_output(seabios_session), re.S)

    error_context.context("Start VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 360))
    seabios_session = vm.logsessions["seabios"]
    rb_timeout = int(params["boot_reboot_timeout"])
    if rb_timeout < 0:
        test.cancel("Do not support rb_timeout = %s" % rb_timeout)
    elif rb_timeout > 65535:
        rb_timeout = 65535

    rb_timeout = rb_timeout // 1000
    pattern = "No bootable device.*Retrying in %d seconds" % rb_timeout

    error_context.context("Check reboot-timeout option", test.log.info)
    if not utils_misc.wait_for(reboot_timeout_check, timeout, 1):
        err = "Guest doesn't reboot in %d seconds" % rb_timeout
        test.fail(err)
    test.log.info(pattern)
