import re

from virttest import error_context, utils_test

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    Balloon service should be in running status after sc interrogate it.
    1) boot a guest with balloon device.
    2) check balloon driver installation status.
    3) enable and check driver verifier in guest.
    4) install and start balloon service in guest.
    5) send INTERROGATE signal to balloon service.
    6) check balloon service status again.
    """

    def interrogate_balloon_service(session):
        """
        Sending INTERROGATE to balloon service.
        :param session: VM session.
        """
        test.log.info("Send INTERROGATE to balloon service")
        sc_interrogate_cmd = params["sc_interrogate_cmd"]
        status, output = session.cmd_status_output(sc_interrogate_cmd)
        if status:
            test.error(output)

    error_context.context("Boot guest with balloon device", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    driver_name = params.get("driver_name", "balloon")

    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_name
    )
    balloon_test = BallooningTestWin(test, params, env)
    err = None
    try:
        # Install and start balloon service in guest
        balloon_test.configure_balloon_service(session)

        # Send INTERROGATE signal to balloon service
        interrogate_balloon_service(session)

        # Check ballloon serivce status again
        output = balloon_test.operate_balloon_service(session, "status")
        if not re.search("running", output.lower(), re.M):
            test.fail(
                "Balloon service is not running after sc interrogate!"
                "Output is: \n %s" % output
            )
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if params.get("os_type") == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    except Exception:
        pass

    finally:
        session.close()
        if err:
            raise err  # pylint: disable=E0702
