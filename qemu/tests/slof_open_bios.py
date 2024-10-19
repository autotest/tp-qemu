"""
slof_open_bios.py include following case:
 1. Disable the auto-boot feature with qemu cli "-prom-env 'auto-boot?=false'".
"""

from virttest import error_context, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify open bios info.

    Step:
     1. Boot guest with qemu cli including "-prom-env 'auto-boot?=false'".
     2. SLOF will not boot automatically, it will go to the SLOF user
        interface directly, and the effect of "-prom-env 'auto-boot?=false'"
        is same with pressing "s" key during boot.
     3. In the SLOF terminal, input "boot" or "reset-all".
     4. SLOF will boot up successfully.
     5. Ping external host ip inside guest successfully.

    :param test: Qemu test object.
    :param params: Dictionary with the test.
    :param env: Dictionary with test environment.
    """

    def _send_custom_key():
        """Send custom keyword to SLOF's user interface."""
        test.log.info('Sending "%s" to SLOF user interface.', send_key)
        for key in send_key:
            key = "minus" if key == "-" else key
            vm.send_key(key)
        vm.send_key("ret")

    vm = env.get_vm(params["main_vm"])
    send_key = params.get("send_key")
    end_str = params.get("slof_end_str", "0 >")
    vm.verify_alive()
    content, next_pos = slof.wait_for_loaded(vm, test, end_str=end_str)
    test.log.info("SLOF stop at '%s'.", end_str)

    error_context.context("Enter to menu by sending '%s'." % send_key, test.log.info)
    _send_custom_key()
    content, _ = slof.wait_for_loaded(vm, test, next_pos, "Trying to load")

    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    session = vm.wait_for_login(timeout=float(params["login_timeout"]))
    test.log.info("log into guest '%s' successfully.", vm.name)

    error_context.context("Try to ping external host.", test.log.info)
    extra_host_ip = utils_net.get_host_ip_address(params)
    session.cmd("ping %s -c 5" % extra_host_ip)
    test.log.info("Ping host(%s) successfully.", extra_host_ip)

    session.close()
    vm.destroy(gracefully=True)
