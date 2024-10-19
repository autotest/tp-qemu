from virttest import error_context, utils_test

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Virtio-win-pvpanic memory leak checking test:
    1) Start a windows guest with device: Pvpanic
    2) Verifying the driver via 'verifier' firstly, then reboot
    3) Re-enter the system, disable the pvpanic and reboot again
    4) checking memory leak after few seconds: BSOD or vm dead
       if leaking occurs
    5) Enabled pvpanic and disabled driver verifier

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    error_context.context(
        "Check if the driver is installed and " "verified", test.log.info
    )
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, params["driver_name"]
    )

    try:
        win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        session.close()
