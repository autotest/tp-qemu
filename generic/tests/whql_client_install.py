import os
import time

from aexpect import rss_client
from virttest import data_dir, remote, utils_misc, utils_test


def run(test, params, env):
    """
    WHQL DTM client installation:
    1) Log into the guest (the client machine) and into a DTM server machine
    2) Stop the DTM client service (wttsvc) on the client machine
    3) Delete the client machine from the server's data store
    4) Rename the client machine (give it a randomly generated name)
    5) Move the client machine into the server's workgroup
    6) Reboot the client machine
    7) Install the DTM client software
    8) Setup auto logon for the user created by the installation
       (normally DTMLLUAdminUser)
    9) Reboot again

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    # Collect test params
    server_address = params.get("server_address")
    server_shell_port = int(params.get("server_shell_port"))
    server_file_transfer_port = int(params.get("server_file_transfer_port"))
    server_studio_path = params.get(
        "server_studio_path",
        "%programfiles%\\ Microsoft Driver Test Manager\\Studio",
    )
    server_username = params.get("server_username")
    server_password = params.get("server_password")
    client_username = params.get("client_username")
    client_password = params.get("client_password")
    dsso_bin = params.get(
        "dsso_delete_machine_binary", "whql/whql_delete_machine_15.exe"
    )
    dsso_delete_machine_binary = os.path.join(data_dir.get_deps_dir(), dsso_bin)
    install_timeout = float(params.get("install_timeout", 600))
    install_cmd = params.get("install_cmd")
    wtt_services = params.get("wtt_services")

    # Stop WTT service(s) on client
    for svc in wtt_services.split():
        utils_test.stop_windows_service(session, svc)

    # Copy dsso_delete_machine_binary to server
    rss_client.upload(
        server_address,
        server_file_transfer_port,
        dsso_delete_machine_binary,
        server_studio_path,
        timeout=60,
    )

    # Open a shell session with server
    server_session = remote.remote_login(
        "nc", server_address, server_shell_port, "", "", session.prompt, session.linesep
    )
    server_session.set_status_test_command(session.status_test_command)

    # Get server and client information
    cmd = "echo %computername%"
    server_name = server_session.cmd_output(cmd).strip()
    client_name = session.cmd_output(cmd).strip()
    cmd = "wmic computersystem get domain"
    server_workgroup = server_session.cmd_output(cmd).strip()
    server_workgroup = server_workgroup.splitlines()[-1]
    regkey = r"HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
    cmd = "reg query %s /v Domain" % regkey
    o = server_session.cmd_output(cmd).strip().splitlines()[-1]
    try:
        server_dns_suffix = o.split(None, 2)[2]
    except IndexError:
        server_dns_suffix = ""

    # Delete the client machine from the server's data store (if it's there)
    server_session.cmd("cd %s" % server_studio_path)
    cmd = "%s %s %s" % (
        os.path.basename(dsso_delete_machine_binary),
        server_name,
        client_name,
    )
    server_session.cmd(cmd, print_func=test.log.info)
    server_session.close()

    # Rename the client machine
    client_name = "autotest_%s" % utils_misc.generate_random_string(4)
    test.log.info("Renaming client machine to '%s'", client_name)
    cmd = (
        'wmic computersystem where name="%%computername%%" rename name="%s"'
        % client_name
    )
    session.cmd(cmd, timeout=600)

    # Join the server's workgroup
    test.log.info("Joining workgroup '%s'", server_workgroup)
    cmd = (
        'wmic computersystem where name="%%computername%%" call '
        'joindomainorworkgroup name="%s"' % server_workgroup
    )
    session.cmd(cmd, timeout=600)

    # Set the client machine's DNS suffix
    test.log.info("Setting DNS suffix to '%s'", server_dns_suffix)
    cmd = 'reg add %s /v Domain /d "%s" /f' % (regkey, server_dns_suffix)
    session.cmd(cmd, timeout=300)

    # Reboot
    session = vm.reboot(session)

    # Access shared resources on the server machine
    test.log.info("Attempting to access remote share on server")
    cmd = r"net use \\%s /user:%s %s" % (server_name, server_username, server_password)
    end_time = time.time() + 120
    while time.time() < end_time:
        try:
            session.cmd(cmd)
            break
        except Exception:
            pass
        time.sleep(5)
    else:
        test.error("Could not access server share from client machine")

    # Install
    test.log.info("Installing DTM client (timeout=%ds)", install_timeout)
    install_cmd = r"cmd /c \\%s\%s" % (server_name, install_cmd.lstrip("\\"))
    session.cmd(install_cmd, timeout=install_timeout)

    # Setup auto logon
    test.log.info("Setting up auto logon for user '%s'", client_username)
    cmd = (
        "reg add "
        '"HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\winlogon" '
        '/v "%s" /d "%s" /t REG_SZ /f'
    )
    session.cmd(cmd % ("AutoAdminLogon", "1"))
    session.cmd(cmd % ("DefaultUserName", client_username))
    session.cmd(cmd % ("DefaultPassword", client_password))

    # Reboot one more time
    session = vm.reboot(session)
    session.close()
