import logging
from virttest import utils_misc
from avocado.core import exceptions


def run(test, params, env):
    """
    This simply stop updates services in Windows guests.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(
        timeout=float(params.get("login_timeout", 240)))

    cmd_timeout = int(params.get("cmd_timeout", 180))
    stop_update_service_cmd = params.get("stop_update_service_cmd")
    if not utils_misc.wait_for(lambda: session.cmd_status(stop_update_service_cmd,
                               timeout=cmd_timeout) == 0, 360, 0, 5):
        raise exceptions.TestFail("Failed to stop Windows update service.")
    logging.info("Stopped Windows updates services.")

    disable_update_service_cmd = params.get("disable_update_service_cmd")
    if not utils_misc.wait_for(lambda: session.cmd_status(disable_update_service_cmd,
                               timeout=cmd_timeout) == 0, 360, 0, 5):
        raise exceptions.TestFail("Turn off updates service failed.")
    logging.info("Turned off windows updates service")
