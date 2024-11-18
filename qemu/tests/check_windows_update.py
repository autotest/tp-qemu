import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check windows update kb list in Windows guests.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(
        timeout=float(params.get("login_timeout", 240)))

    cmd_timeout = float(params.get("cmd_timeout", 180))
    install_nuget = params["install_nuget"]
    install_pswindowsupdate = params["install_pswindowsupdate"]
    check_windows_update = params["check_windows_update"]
    set_powershell_policy = params["set_powershell_policy"]

    session.cmd("sc config WuAuServ start= auto")

    session = vm.reboot(session)
    error_context.context("Setting powershell policy", test.log.info)
    
    status, results = session.cmd_status_output(cmd=set_powershell_policy,
                                                timeout=cmd_timeout)

    if status != 0:
        test.fail("Setting powershell policy failed: %s" % results)

    error_context.context("Install install_nuget package in PS",
                          test.log.info)
    
    status, results = session.cmd_status_output(cmd=install_nuget,
                                                timeout=cmd_timeout)

    if status != 0:
        test.fail("Install nuget package failed: %s" % results)

    error_context.context("Install PSWindowsUpdate module in PS",
                          test.log.info)
    
    status, results = session.cmd_status_output(cmd=install_pswindowsupdate,
                                                timeout=cmd_timeout)

    if status != 0:
        test.fail("Install PSWindowsUpdate module failed: %s" % results)

    error_context.context("Check windows updates kb list", test.log.info)

    status, results = session.cmd_status_output(cmd=check_windows_update,
                                                timeout=cmd_timeout)
    if status != 0:
        test.fail("Check windows updates kb list failed: %s" % results)

    filename = "/home/" + params["guest_name"] + '-kblist.txt'
    with open(filename, 'w+') as f:
        f.write(str(results))
    session.close()
