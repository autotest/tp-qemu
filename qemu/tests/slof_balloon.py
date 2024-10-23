"""
slof_balloon.py include following case:
 1. virtio balloon can work with pci-bridge.
"""

from virttest import error_context, utils_misc, utils_net

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify SLOF info with balloon.

    Step:
     1. Boot a guest with virtio-balloon and pci-bridge.
      1.1. Check if any error info in output of SLOF during booting.
      1.2. Guest could log in successfully.
     2. Check virtio balloon device and change its value
      2.1 Set the value of balloon.
      2.2 Guest could ping external host ip successfully.

    :param test: Qemu test object.
    :param params: Dictionary with the test .
    :param env: Dictionary with test environment.
    """

    def _get_qmp_port():
        """Get the qmp monitor port."""
        qmp_ports = vm.get_monitors_by_type("qmp")
        if not qmp_ports:
            test.error("Incorrect configuration, no QMP monitor found.")
        return qmp_ports[0]

    def _check_balloon_info():
        """Check virtio balloon device info."""
        error_context.context("Check virtio balloon device info.")
        balloon_size = qmp.query("balloon")["actual"]
        test.log.debug("The balloon size is %s", balloon_size)
        mem = int(params["mem"]) * 1024**2
        if int(balloon_size) != mem:
            test.error("The balloon size is not equal to %d" % mem)

    def _change_balloon_size():
        """Change the ballloon size."""
        changed_ballon_size = int(params["balloon_size"])
        balloon_timeout = int(params["balloon_timeout"])
        error_context.context("Change the balloon size to %s" % changed_ballon_size)
        qmp.balloon(changed_ballon_size)
        error_context.context("Check balloon size after changed.")
        if not utils_misc.wait_for(
            lambda: bool(changed_ballon_size == int(qmp.query("balloon")["actual"])),
            balloon_timeout,
        ):
            test.fail(
                "The balloon size is not changed to %s in %s sec."
                % (changed_ballon_size, balloon_timeout)
            )
        test.log.debug("The balloon size is %s after changed.", changed_ballon_size)

    def _ping_host():
        """Ping host from guest."""
        error_context.context("Try to ping external host.", test.log.info)
        extra_host_ip = utils_net.get_host_ip_address(params)
        session.cmd("ping %s -c 5" % extra_host_ip)
        test.log.info("Ping host(%s) successfully.", extra_host_ip)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    content, _ = slof.wait_for_loaded(vm, test)

    error_context.context("Check the output of SLOF.", test.log.info)
    slof.check_error(test, content)

    error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
    session = vm.wait_for_login(timeout=float(params.get("login_timeout", 240)))
    test.log.info("log into guest '%s' successfully.", vm.name)

    qmp = _get_qmp_port()
    _check_balloon_info()
    _change_balloon_size()
    _ping_host()

    session.close()
    vm.destroy(gracefully=True)
