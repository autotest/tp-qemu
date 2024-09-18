from virttest import utils_test


def run(test, params, env):
    """
    Test to check whether the error event is logged.

    Steps:
        1) Start guest with multiple virtio-blk disks.
        2) Install the virtio-blk driver.
        3) Go to Windows Logs to check if have the corresponding
           error event.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def query_system_events(filter_options):
        """Query the system events in filter options."""
        test.log.info("Query the system event log.")
        cmd = 'wevtutil qe system /q:"%s" /f:text' % filter_options
        return session.cmd(cmd).strip()

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = utils_test.qemu.windrv_check_running_verifier(
        vm.wait_for_login(), vm, test, "viostor", 300
    )

    if query_system_events(params["filter_options"]):
        test.fail("Found the error event(id: %s)." % params["event_id"])
